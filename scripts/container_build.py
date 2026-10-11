#!/usr/bin/env python3
"""Offline source compiler and regular-file image assembler. Run in Docker.

Bootlin's compiler/sysroot and SeedSigner's signed OS are explicit trusted
binary inputs. The gpSP core and embedded open BIOS are compiled here; the
prebuilt BIOS in the upstream source archive is deleted before compilation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tarfile
import zlib

from release import ROOT, EPOCH, fetch, load_lock, sha, verify_rom
from verify_inputs import verify_signature
from build_image import Fat16, build as assemble_image

WORK = ROOT / "build/work"
ARTIFACTS = ROOT / "artifacts"


def run(command, cwd=ROOT, capture=False, env=None):
    print("+ " + " ".join(str(x) for x in command), flush=True)
    return subprocess.check_output(command, cwd=cwd, env=env, text=True) if capture else subprocess.run(command, cwd=cwd, env=env, check=True)


def extract(archive, destination):
    destination.mkdir(parents=True)
    with tarfile.open(archive) as stream:
        # Debian's Python 3.11 lacks tarfile's newer data filter. Check every
        # destination/link before extraction; inputs have already matched locks.
        for member in stream.getmembers():
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts or member.isdev() or member.isfifo():
                raise ValueError("Unsafe source archive member")
            target = destination.joinpath(*name.parts)
            if not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError("Source archive path escapes its destination")
            if member.issym() or member.islnk():
                link = PurePosixPath(member.linkname)
                base = target.parent if member.issym() else destination
                if link.is_absolute() or not base.joinpath(*link.parts).resolve().is_relative_to(destination.resolve()):
                    raise ValueError("Source archive link escapes its destination")
            if not (member.isdir() or member.isfile() or member.issym() or member.islnk()):
                raise ValueError("Unsupported source archive entry")
            stream.extract(member, destination)
    roots = list(destination.iterdir())
    if len(roots) != 1 or not roots[0].is_dir():
        raise ValueError("Expected a single archive root")
    return roots[0]


def gzip_members(data):
    for match in re.finditer(re.escape(b"\x1f\x8b\x08"), data):
        try:
            decoder = zlib.decompressobj(31)
            content = decoder.decompress(data[match.start():])
            if decoder.eof:
                yield content
        except zlib.error:
            pass


def stock_libraries(base, destination):
    """Extract only /lib from the already verified stock kernel for QEMU ABI checks."""
    kernel = Fat16(base.read_bytes()).files["zImage"]
    archives = [cpio for expanded in gzip_members(kernel) for cpio in gzip_members(expanded) if cpio.startswith(b"070701")]
    if len(archives) != 1:
        raise ValueError("Expected exactly one stock built-in rootfs")
    cpio, offset, selected = archives[0], 0, []
    while True:
        header = cpio[offset:offset + 110]
        if len(header) != 110 or header[:6] != b"070701":
            raise ValueError("Invalid stock newc header")
        fields = [int(header[i:i + 8], 16) for i in range(6, 110, 8)]
        mode, size, namesize = fields[1], fields[6], fields[11]
        name = cpio[offset + 110:offset + 110 + namesize - 1].decode()
        at = (offset + 110 + namesize + 3) & ~3
        body = cpio[at:at + size]
        offset = (at + size + 3) & ~3
        if len(body) != size:
            raise ValueError("Truncated stock rootfs entry")
        if name == "TRAILER!!!":
            break
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unsafe stock rootfs path")
        if relative.parts[:1] != ("lib",):
            continue
        target = destination.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        # A prior link must never become a write destination or parent.
        if any(p.is_symlink() for p in [target, *target.parents] if p != destination.parent):
            raise ValueError("Unsafe stock library extraction order")
        if stat.S_ISDIR(mode):
            target.mkdir(exist_ok=True)
        elif stat.S_ISREG(mode):
            target.write_bytes(body)
            target.chmod(stat.S_IMODE(mode))
            selected.append({"path": name, "sha256": hashlib.sha256(body).hexdigest()})
        elif stat.S_ISLNK(mode):
            link = body.decode()
            if PurePosixPath(link).is_absolute() or ".." in PurePosixPath(link).parts:
                raise ValueError("Escaping stock library link")
            target.symlink_to(link)
            selected.append({"path": name, "symlink": link})
    return {"kernel_sha256": hashlib.sha256(kernel).hexdigest(), "libraries": selected}


def build_bios(gpsp, tonc):
    original = gpsp / "bios/open_gba_bios.bin"
    ignored_hash = sha(original)
    original.unlink()
    objects = []
    for source in sorted((gpsp / "bios/source").iterdir()):
        if source.suffix not in (".c", ".s"):
            continue
        output = WORK / (source.name + ".o")
        flags = ["-mcpu=arm7tdmi", "-marm", "-mthumb-interwork", "-O2", "-std=c99",
                 "-ffreestanding", "-fno-builtin", "-fno-stack-protector", "-fno-unwind-tables",
                 "-fno-asynchronous-unwind-tables", "-fno-ident", "-ffile-prefix-map=/work=.",
                 "-I" + str(tonc / "include"), "-isystem", "/usr/include/newlib"]
        run(["arm-none-eabi-gcc", *flags, "-c", str(source), "-o", str(output)])
        objects.append(output)
    elf = WORK / "open-bios.elf"
    run(["arm-none-eabi-gcc", "-mcpu=arm7tdmi", "-marm", "-nostdlib", "-Wl,--build-id=none",
         "-T", str(ROOT / "build/bios.ld"), "-o", str(elf), *map(str, objects), "-lgcc"])
    run(["arm-none-eabi-objcopy", "--pad-to", "0x4000", "-O", "binary", str(elf), str(original)])
    if original.stat().st_size != 16384:
        raise ValueError("Open BIOS must be 16 KiB")
    shutil.copy2(original, ARTIFACTS / "open_gba_bios.bin")
    return {"sha256": sha(original), "upstream_prebuilt_bios_ignored_sha256": ignored_hash,
            "compiler": run(["arm-none-eabi-gcc", "--version"], capture=True).splitlines()[0],
            "link_recipe": "build/bios.ld; ARM7TDMI, freestanding, no Nintendo BIOS"}


def elf_check(binary, readelf):
    text = run([readelf, "-A", str(binary)], capture=True)
    if "Tag_CPU_arch: v6" not in text or "Tag_FP_arch: VFPv2" not in text or "Tag_ABI_VFP_args: VFP registers" not in text:
        raise ValueError("Binary does not declare ARMv6/VFPv2 hard-float ABI: " + binary.name)
    if re.search(r"Tag_CPU_arch: v[789]|NEON|Advanced_SIMD", text):
        raise ValueError("Binary declares instructions newer than the Pi Zero")
    return text.strip().splitlines()


def build_all(native_only=False):
    if WORK.exists() or ARTIFACTS.exists():
        raise ValueError("Build requires a fresh container workspace")
    fetch(offline=True)
    signed = verify_signature()
    lock = load_lock()
    WORK.mkdir(parents=True)
    ARTIFACTS.mkdir()
    inputs = {name: ROOT / "downloads" / data["file"] for name, data in lock["inputs"].items()}
    compiler_root = extract(inputs["toolchain"], WORK / "toolchain")
    relocate = compiler_root / "relocate-sdk.sh"
    if relocate.exists():
        run(["bash", str(relocate)], cwd=compiler_root)
    prefix = str(compiler_root / "bin/arm-buildroot-linux-gnueabihf-")
    cc, readelf = prefix + "gcc", prefix + "readelf"
    gpsp = extract(inputs["gpsp"], WORK / "gpsp")
    tonc = extract(inputs["libtonc"], WORK / "libtonc")
    bios = build_bios(gpsp, tonc)
    flags = "-fno-ident -ffile-prefix-map=/work=. -fdebug-prefix-map=/work=."
    environment = {**os.environ, "CFLAGS": flags}
    run(["make", "-j2", "platform=rpi1", "CC=" + cc, "AR=" + prefix + "ar", "GIT_VERSION= e554360",
         "LDFLAGS=-Wl,--build-id=none -Wl,-z,noexecstack"], cwd=gpsp, env=environment)
    core = ARTIFACTS / "gpsp_libretro.so"
    shutil.copy2(gpsp / core.name, core)
    abi = {"gpsp": elf_check(core, readelf)}
    runtime = WORK / "stock-runtime"
    stock = stock_libraries(inputs["seedsigner_os"], runtime)
    # Keep guest addresses below 4 GiB, at a separate host base. The explicit
    # base also permits ARM QEMU inside amd64 emulation on an ARM Docker host.
    qemu = ["qemu-arm", "-R", "0xfffff000", "-B", "0x100000000", "-cpu", "arm1176", "-L", str(runtime)]
    results = {}
    for profile, width in (("regular", 240), ("plus", 320)):
        output = ARTIFACTS / profile
        output.mkdir()
        binary = output / "dino-native"
        run([cc, "-O3", "-std=c99", "-Wall", "-Wextra", "-Werror", "-fno-strict-aliasing",
             "-marm", "-march=armv6", "-mfpu=vfp", "-mfloat-abi=hard", "-fno-ident",
             "-ffile-prefix-map=/work=.", "-Wl,--build-id=none", "-DDINO_LCD_WIDTH=" + str(width),
             "-o", str(binary), str(ROOT / "native/dino_frontend.c"), "-ldl"])
        abi[profile] = elf_check(binary, readelf)
        results[profile] = {"self_test": json.loads(run([*qemu, str(binary), "--self-test"], capture=True))}
    # Load/initialize the compiled core with the stock OS libraries even without a ROM.
    probe = WORK / "core-probe.c"
    probe.write_text('#include <dlfcn.h>\nint main(int n,char **v){void*h=dlopen(v[1],RTLD_NOW);if(!h)return 1;unsigned(*api)(void)=dlsym(h,"retro_api_version");if(!api||api()!=1)return 2;dlclose(h);return n!=2;}\n')
    run([cc, "-march=armv6", "-mfpu=vfp", "-mfloat-abi=hard", "-o", str(WORK / "core-probe"), str(probe), "-ldl"])
    run([*qemu, str(WORK / "core-probe"), str(core)])
    manifest = {"schema": 1, "version": lock["project_version"], "inputs": lock,
        "signed_base": signed, "project_source_archive_sha256": sha(ROOT / "project-source.tar.gz"),
        "toolchain_version": run([cc, "--version"], capture=True).splitlines()[0],
        "debian_packages": run(["dpkg-query", "-W", "-f=${Package}=${Version}\n"], capture=True).splitlines(),
        "open_bios": bios, "ELF_attributes": abi, "stock_runtime": stock, "QEMU_checks": results,
        "physical_device_tested": False, "public_image_release_approved": False,
        "reproducibility_boundary": "Own frontend, gpSP and open BIOS compiled from pinned source. Bootlin compiler/sysroot, Debian tools and signed SeedSigner OS are trusted binary inputs. ROM1.1 is a trusted upstream release binary, not rebuilt from source. Repeated builds must be compared; QEMU is not hardware validation or a security guarantee.",
        "files": {p.relative_to(ARTIFACTS).as_posix(): sha(p) for p in sorted(ARTIFACTS.rglob("*")) if p.is_file()}}
    (ARTIFACTS / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if not native_only:
        from package_release import package_images
        package_images(ARTIFACTS, ARTIFACTS, ROOT / "local-rom.gba",
                       ROOT / "project-source.tar.gz", reuse=False)
    (ARTIFACTS / "SHA256SUMS").write_text("".join(sha(p) + "  " + p.relative_to(ARTIFACTS).as_posix() + "\n"
                                               for p in sorted(ARTIFACTS.rglob("*")) if p.is_file() and p.name != "SHA256SUMS"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-only", action="store_true")
    build_all(parser.parse_args().native_only)

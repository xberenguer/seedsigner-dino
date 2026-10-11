#!/usr/bin/env python3
"""Assemble experimental images from accounted-for native builds and ROM1.1.

Package-only reuse accepts exactly the previously source-built, QEMU-checked
native bundle. Runtime source equality is checked against its archived snapshot.
This neither writes a physical device nor asserts hardware/security validation.
"""
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import tempfile

from release import ROOT, SOURCE_NAME, checked, fetch, load_lock, prepare_rom, sha, source
from verify_inputs import verify_signature
from build_image import build as assemble_image

CACHE_LOCK = ROOT / 'build/native-cache.lock.json'


def runtime_sources():
    files = [ROOT / 'native/dino_frontend.c', ROOT / 'native/libretro.h']
    files.extend(p for p in (ROOT / 'payload').rglob('*') if p.is_file())
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(files)}


def verify_cached_native(directory):
    directory = Path(directory)
    cache = json.loads(CACHE_LOCK.read_text())
    manifest_path = checked(directory / 'build-manifest.json', cache['manifest_sha256'])
    manifest = json.loads(manifest_path.read_text())
    lock = load_lock()
    source_input = lock['inputs'][cache['project_source_input']]
    archive = checked(ROOT / 'downloads' / source_input['file'], source_input['sha256'])
    if manifest['project_source_archive_sha256'] != source_input['sha256']:
        raise ValueError('Native build source snapshot differs from its lock')
    for key in ('toolchain', 'gpsp', 'libtonc', 'seedsigner_os'):
        if manifest['inputs']['inputs'][key]['sha256'] != lock['inputs'][key]['sha256']:
            raise ValueError('Native build dependency differs: ' + key)
    for name, expected in cache['files'].items():
        checked(directory / name, expected)
        if manifest['files'][name] != expected:
            raise ValueError('Native build manifest disagrees: ' + name)
    for profile in ('regular', 'plus'):
        if manifest['QEMU_checks'][profile]['self_test']['self_test'] != 'PASS':
            raise ValueError('Cached frontend lacks passing ARM1176 self-tests')
    actual = runtime_sources()
    with tarfile.open(archive) as stream:
        archived = {member.name.removeprefix('seedsigner-dino/'): member for member in stream.getmembers()}
        expected_names = {name for name in archived if name.startswith('payload/')} | {'native/dino_frontend.c', 'native/libretro.h'}
        if set(actual) != expected_names:
            raise ValueError('Runtime source inventory changed; rebuild native instead of cache reuse')
        for name, digest in actual.items():
            member = archived[name]
            if not member.isfile() or hashlib.sha256(stream.extractfile(member).read()).hexdigest() != digest:
                raise ValueError('Runtime source changed since cached compilation: ' + name)
    return manifest, actual


def game_notices(destination):
    lock = load_lock()
    item = lock['inputs'][lock['licensed_rom']['source_input']]
    archive = checked(ROOT / 'downloads' / item['file'], item['sha256'])
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as stream:
        members = stream.getmembers()
        root = members[0].name.split('/')[0]
        for name, expected in lock['licensed_rom']['license_files'].items():
            matches = [member for member in members if member.name == root + '/' + name]
            if len(matches) != 1 or not matches[0].isfile():
                raise ValueError('Game source license missing or duplicate: ' + name)
            data = stream.extractfile(matches[0]).read()
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError('Game source license hash differs: ' + name)
            target = destination / ('MIT-LICENSE.txt' if name == 'LICENSE' else Path(name).name)
            target.write_bytes(data)


def additional_notices(destination):
    lock = load_lock()
    destination.mkdir(parents=True, exist_ok=True)
    for key, suffix, filename in (
            ('gpsp', '/COPYING', 'gpSP-COPYING.txt'),
            ('gba_toolchain_source', '/LICENSE.md', 'gba-toolchain-librom-zlib.txt'),
            ('maxmod_license_reference', '/include/maxmod.h', 'maxmod-ISC-reference.txt')):
        item = lock['inputs'][key]
        archive = checked(ROOT / 'downloads' / item['file'], item['sha256'])
        with tarfile.open(archive) as stream:
            members = [member for member in stream.getmembers() if member.name.endswith(suffix)]
            if len(members) != 1 or not members[0].isfile():
                raise ValueError('Third-party notice missing or duplicate: ' + key)
            data = stream.extractfile(members[0]).read()
        if key == 'maxmod_license_reference':
            # Preserve the exact upstream ISC block without implying this current
            # reference commit was the unknown version linked into ROM1.1.
            if not data.startswith(b'/*') or b'*/' not in data:
                raise ValueError('Maxmod ISC header not recognized')
            data = data[:data.index(b'*/') + 2] + b'\n\nReference only: exact maxmod version used by official ROM1.1 is unknown.\n'
        (destination / filename).write_bytes(data)


def package_images(native_dir, output, rom=None, source_archive=None, reuse=True):
    """reuse=False is only called after compilation in the isolated build container."""
    fetch(offline=True)
    signed = verify_signature()
    lock = load_lock()
    rom = prepare_rom(rom)
    native_dir, output = Path(native_dir), Path(output)
    if reuse:
        native_manifest, runtime_hashes = verify_cached_native(native_dir)
        if output.exists():
            raise ValueError('Refusing existing package output directory')
        output.mkdir(parents=True)
    else:
        native_manifest = json.loads((native_dir / 'build-manifest.json').read_text())
        runtime_hashes = runtime_sources()
        for name in ('regular/dino-native', 'plus/dino-native', 'gpsp_libretro.so', 'open_gba_bios.bin'):
            checked(native_dir / name, native_manifest['files'][name])
        if native_manifest['project_source_archive_sha256'] != sha(source_archive):
            raise ValueError('Fresh native build does not identify its corresponding source archive')
    if source_archive is None:
        source(output)
        project_source = output / SOURCE_NAME
    else:
        project_source = Path(source_archive)
        shutil.copy2(project_source, output / SOURCE_NAME)
        project_source = output / SOURCE_NAME
    compiled_source = ROOT / 'downloads' / lock['inputs']['compiled_project_source']['file'] if reuse else project_source
    inputs = {name: ROOT / 'downloads' / item['file'] for name, item in lock['inputs'].items()}
    provenance = {
        'schema': 1, 'version': lock['project_version'], 'signed_base': signed,
        'native_build_reused': reuse, 'native_build_manifest_sha256': sha(native_dir / 'build-manifest.json'),
        'compiled_project_source_sha256': sha(compiled_source), 'project_source_sha256': sha(project_source),
        'runtime_source_files_sha256': runtime_hashes, 'native_files': native_manifest['files'],
        'ROM': {**lock['licensed_rom'], 'source_commit': lock['inputs']['dino_rom_source']['commit'],
                'source_to_binary_reproduced': False, 'trusted_upstream_release_binary': True},
        'physical_device_tested': False, 'physical_device_written': False,
        'reproducibility_boundary': 'Deterministic image assembly from exact inputs. Native frontend/gpSP/open BIOS were built from pinned source; toolchain and stock OS are trusted binaries. ROM1.1 is the exact official release binary, not reproduced from source. QEMU and readback do not establish hardware behavior or security.'}
    for profile in ('regular', 'plus'):
        with tempfile.TemporaryDirectory(prefix='dino-package-') as temporary:
            stage = Path(temporary) / 'payload'
            shutil.copytree(ROOT / 'payload', stage, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
            native = stage / 'opt/dino/native'
            if native.exists() and list(native.iterdir()):
                raise ValueError('Source payload contains unaccounted-for native inputs')
            native.mkdir(parents=True, exist_ok=True)
            shutil.copy2(native_dir / profile / 'dino-native', native / 'dino-native')
            shutil.copy2(native_dir / 'gpsp_libretro.so', native / 'gpsp_libretro.so')
            shutil.copy2(rom, native / lock['licensed_rom']['file'])
            (stage / 'opt/dino/display-profile.json').write_text(json.dumps({'profile': profile}, sort_keys=True) + '\n')
            sources = stage / 'opt/dino/licenses/sources'
            sources.mkdir(parents=True, exist_ok=True)
            for key in ('gpsp', 'libtonc', 'dino_rom_source', 'gba_toolchain_source', 'maxmod_license_reference'):
                shutil.copy2(inputs[key], sources / inputs[key].name)
            shutil.copy2(project_source, sources / SOURCE_NAME)
            if compiled_source != project_source:
                shutil.copy2(compiled_source, sources / compiled_source.name)
            game_notices(stage / 'opt/dino/licenses/Google-Dino-GBA-1.1')
            additional_notices(stage / 'opt/dino/licenses/third-party')
            shutil.copy2(ROOT / 'LICENSE', stage / 'opt/dino/licenses/SeedSigner-Dino-GPL-2.0.txt')
            shutil.copy2(ROOT / 'native/NOTICE.txt', stage / 'opt/dino/licenses/native-NOTICE.txt')
            # Current provenance is authoritative; retain exact historical native evidence as a separate record.
            (stage / 'opt/dino/native-build.json').write_text(json.dumps({**provenance, 'profile': profile}, indent=2) + '\n')
            shutil.copy2(native_dir / 'build-manifest.json', stage / 'opt/dino/native-compile-manifest.json')
            filename = f"seedsigner-v{lock['seedsigner_version']}-dino-v{lock['project_version']}-{profile}-pi0.img"
            assemble_image(inputs['seedsigner_os'], stage, output / filename, profile=profile)
    provenance['images'] = {p.name: sha(p) for p in sorted(output.glob('*.img'))}
    (output / 'image-build-manifest.json').write_text(json.dumps(provenance, indent=2) + '\n')
    (output / 'SHA256SUMS').write_text(''.join(sha(p) + '  ' + p.name + '\n' for p in sorted(output.iterdir()) if p.is_file() and p.name != 'SHA256SUMS'))
    print(json.dumps({'images': provenance['images'], 'physical_device_tested': False}, indent=2))
    return provenance

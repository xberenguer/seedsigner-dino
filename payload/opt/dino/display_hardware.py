"""Rectangle adapter for the upstream original 240x240 display driver."""


class RegularDisplayAdapter:
    """Keep upstream initialization while exposing the game's packed RGB565 API."""

    def __init__(self, driver, gpio, pack_pixels):
        self.driver, self.gpio, self.pack_pixels = driver, gpio, pack_pixels

    @property
    def width(self):
        return self.driver.width

    @property
    def height(self):
        return self.driver.height

    @property
    def spi(self):
        return self.driver._spi

    def blit_buffer(self, data, x, y, width, height):
        if (not all(isinstance(value, int) for value in (x, y, width, height))
                or width <= 0 or height <= 0 or x < 0 or y < 0
                or x + width > self.width or y + height > self.height
                or len(data) != width * height * 2):
            raise ValueError("Rectangle does not fit regular display")
        # Original SetWindows takes exclusive end coordinates.
        self.driver.SetWindows(x, y, x + width, y + height)
        self.gpio.output(self.driver._dc, self.gpio.HIGH)
        self.spi.writebytes2(data)

    def show_image(self, image, x_start=0, y_start=0):
        if image.size != (self.width, self.height) or x_start != 0 or y_start != 0:
            raise ValueError("Full image must match display dimensions")
        self.blit_buffer(self.pack_pixels(image.convert("RGB")),
                         0, 0, self.width, self.height)

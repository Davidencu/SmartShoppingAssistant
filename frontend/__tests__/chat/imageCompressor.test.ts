import { compressImage } from "@/lib/imageCompressor";

// ─── Canvas / Image mocks ─────────────────────────────────────────────────────

const mockDrawImage = jest.fn();
const mockToDataURL = jest.fn(() => "data:image/webp;base64,Y29tcHJlc3NlZA==");
const mockGetContext = jest.fn(() => ({ drawImage: mockDrawImage }));

let mockImgOnLoad: (() => void) | null = null;

beforeEach(() => {
  jest.clearAllMocks();

  jest.spyOn(document, "createElement").mockImplementation((tag: string) => {
    if (tag === "canvas") {
      return {
        getContext: mockGetContext,
        toDataURL: mockToDataURL,
        width: 0,
        height: 0,
      } as unknown as HTMLElement;
    }
    return document.createElement(tag);
  });

  // Mock the Image constructor so img.onload fires synchronously
  Object.defineProperty(globalThis, "Image", {
    writable: true,
    configurable: true,
    value: class MockImage {
      width = 2000;
      height = 1500;
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      set src(_v: string) {
        mockImgOnLoad = this.onload;
        Promise.resolve().then(() => this.onload?.());
      }
    },
  });

  URL.createObjectURL = jest.fn(() => "blob:fake-url");
  URL.revokeObjectURL = jest.fn();
});

afterEach(() => {
  jest.restoreAllMocks();
});

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("compressImage", () => {
  const makeFile = (name = "photo.jpg", type = "image/jpeg") =>
    new File(["fake-bytes"], name, { type });

  it("resolves with a base64 string (no data URL prefix)", async () => {
    const result = await compressImage(makeFile());
    expect(result).toBe("Y29tcHJlc3NlZA==");
    expect(result).not.toContain("data:image/webp;base64,");
  });

  it("scales width down to 1024px when source is wider", async () => {
    await compressImage(makeFile());
    const canvas = (document.createElement as jest.Mock).mock.results.find(
      (r) => r.value?.getContext
    )?.value;
    expect(canvas?.width).toBe(1024);
  });

  it("preserves aspect ratio when scaling (2000×1500 → 1024×768)", async () => {
    await compressImage(makeFile());
    const canvas = (document.createElement as jest.Mock).mock.results.find(
      (r) => r.value?.getContext
    )?.value;
    expect(canvas?.height).toBe(768);
  });

  it("does not upscale images narrower than 1024px", async () => {
    Object.defineProperty(globalThis, "Image", {
      writable: true,
      configurable: true,
      value: class MockSmallImage {
        width = 640;
        height = 480;
        onload: (() => void) | null = null;
        onerror: (() => void) | null = null;
        set src(_v: string) {
          Promise.resolve().then(() => this.onload?.());
        }
      },
    });

    await compressImage(makeFile());
    const canvas = (document.createElement as jest.Mock).mock.results.find(
      (r) => r.value?.getContext
    )?.value;
    expect(canvas?.width).toBe(640);
    expect(canvas?.height).toBe(480);
  });

  it("exports with image/webp and 0.7 quality", async () => {
    await compressImage(makeFile());
    expect(mockToDataURL).toHaveBeenCalledWith("image/webp", 0.7);
  });

  it("rejects when the image fails to load", async () => {
    Object.defineProperty(globalThis, "Image", {
      writable: true,
      configurable: true,
      value: class ErrorImage {
        width = 0;
        height = 0;
        onload: (() => void) | null = null;
        onerror: (() => void) | null = null;
        set src(_v: string) {
          Promise.resolve().then(() => this.onerror?.());
        }
      },
    });

    await expect(compressImage(makeFile())).rejects.toThrow("Failed to load image");
  });

  it("rejects when canvas context is unavailable", async () => {
    mockGetContext.mockReturnValueOnce(null);
    await expect(compressImage(makeFile())).rejects.toThrow("Canvas 2D context unavailable");
  });
});

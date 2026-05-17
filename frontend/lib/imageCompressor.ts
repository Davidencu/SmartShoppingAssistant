const MAX_WIDTH = 1024;
const WEBP_QUALITY = 0.7;

/**
 * Compress an image file in the browser before base64-encoding it.
 * - Draws the image onto an invisible <canvas>
 * - Scales down to MAX_WIDTH if wider (preserves aspect ratio)
 * - Exports as WEBP at WEBP_QUALITY
 * A 5 MB JPG typically becomes ~150 KB WEBP (~200 KB base64 string).
 */
export function compressImage(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const objectUrl = URL.createObjectURL(file);

    img.onload = () => {
      URL.revokeObjectURL(objectUrl);

      const scale = img.width > MAX_WIDTH ? MAX_WIDTH / img.width : 1;
      const width = Math.round(img.width * scale);
      const height = Math.round(img.height * scale);

      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;

      const ctx = canvas.getContext("2d");
      if (!ctx) {
        reject(new Error("Canvas 2D context unavailable"));
        return;
      }

      ctx.drawImage(img, 0, 0, width, height);

      const dataUrl = canvas.toDataURL("image/webp", WEBP_QUALITY);
      // Strip the data URL prefix ("data:image/webp;base64,")
      const base64 = dataUrl.split(",")[1];
      if (!base64) {
        reject(new Error("Failed to encode image as base64"));
        return;
      }
      resolve(base64);
    };

    img.onerror = () => {
      URL.revokeObjectURL(objectUrl);
      reject(new Error("Failed to load image"));
    };

    img.src = objectUrl;
  });
}

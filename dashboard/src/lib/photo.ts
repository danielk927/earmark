/** Client-side photo shrinking: a JPEG under MAX_BYTES before anything leaves the device. */

export const MAX_BYTES = 950_000;
const EDGES = [1600, 1280, 1024, 800];
const QUALITIES = [0.85, 0.72, 0.6];

export class PhotoError extends Error {}

function toBlob(canvas: HTMLCanvasElement, quality: number): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", quality));
}

export async function downscalePhoto(file: Blob): Promise<Blob> {
  if (!file.type.startsWith("image/")) throw new PhotoError("That file is not an image. Choose a photo instead.");
  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  } catch {
    throw new PhotoError("This browser could not open that photo. Try a JPEG or PNG.");
  }
  try {
    for (const edge of EDGES) {
      const scale = Math.min(1, edge / Math.max(bitmap.width, bitmap.height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(bitmap.width * scale));
      canvas.height = Math.max(1, Math.round(bitmap.height * scale));
      const ctx = canvas.getContext("2d");
      if (!ctx) throw new PhotoError("This browser could not resize the photo.");
      ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      for (const q of QUALITIES) {
        const blob = await toBlob(canvas, q);
        if (blob && blob.size <= MAX_BYTES) return blob;
      }
    }
  } finally {
    bitmap.close();
  }
  throw new PhotoError("The photo is still too large after shrinking. Try a different photo.");
}

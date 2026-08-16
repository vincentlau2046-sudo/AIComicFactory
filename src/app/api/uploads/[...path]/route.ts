import { NextResponse } from "next/server";
import fs from "node:fs";
import path from "node:path";
import { getUploadDir } from "@/lib/env";

const uploadDir = getUploadDir();

const MIME_TYPES: Record<string, string> = {
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
  ".mp4": "video/mp4",
  ".webm": "video/webm",
};

export async function GET(
  request: Request,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path: segments } = await params;
  const filePath = path.join(uploadDir, ...segments);

  // Prevent directory traversal
  const resolved = path.resolve(filePath);
  const resolvedUploadDir = path.resolve(uploadDir);
  if (!resolved.startsWith(resolvedUploadDir)) {
    return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  }

  if (!fs.existsSync(resolved)) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  const fileSize = fs.statSync(resolved).size;
  const ext = path.extname(resolved).toLowerCase();
  const contentType = MIME_TYPES[ext] || "application/octet-stream";

  const rangeHeader = request.headers.get("range");

  if (rangeHeader) {
    // Parse Range header: bytes=<start>-<end>
    const match = rangeHeader.match(/bytes=(\d*)-(\d*)/);
    if (!match) {
      // Malformed range — fall back to full file
      const buffer = fs.readFileSync(resolved);
      return new NextResponse(buffer, {
        status: 200,
        headers: {
          "Content-Type": contentType,
          "Content-Length": String(fileSize),
          "Accept-Ranges": "bytes",
        },
      });
    }

    const start = match[1] ? parseInt(match[1], 10) : 0;
    const end = match[2] ? parseInt(match[2], 10) : fileSize - 1;
    const clampedEnd = Math.min(end, fileSize - 1);

    // Handle suffix range (-500)
    if (match[1] === "" && match[2]) {
      const suffix = parseInt(match[2], 10);
      const realStart = Math.max(0, fileSize - suffix);
      const buffer = fs.readFileSync(resolved, { flag: "r" });
      const chunk = buffer.subarray(realStart);
      return new NextResponse(chunk, {
        status: 206,
        headers: {
          "Content-Type": contentType,
          "Content-Length": String(chunk.length),
          "Content-Range": `bytes ${realStart}-${fileSize - 1}/${fileSize}`,
          "Accept-Ranges": "bytes",
        },
      });
    }

    if (start >= fileSize || start > clampedEnd) {
      return NextResponse.json(
        { error: "Range Not Satisfiable" },
        { status: 416, headers: { "Content-Range": `bytes */${fileSize}` } }
      );
    }

    // For range requests, read only the requested bytes
    const chunkSize = clampedEnd - start + 1;
    const buffer = Buffer.alloc(chunkSize);
    const fd = fs.openSync(resolved, fs.constants.O_RDONLY);
    try {
      fs.readSync(fd, buffer, 0, chunkSize, start);
    } finally {
      fs.closeSync(fd);
    }

    return new NextResponse(buffer, {
      status: 206,
      headers: {
        "Content-Type": contentType,
        "Content-Length": String(chunkSize),
        "Content-Range": `bytes ${start}-${clampedEnd}/${fileSize}`,
        "Accept-Ranges": "bytes",
      },
    });
  }

  // Full file response (non-Range clients)
  const buffer = fs.readFileSync(resolved);
  return new NextResponse(buffer, {
    status: 200,
    headers: {
      "Content-Type": contentType,
      "Content-Length": String(fileSize),
      "Accept-Ranges": "bytes",
    },
  });
}
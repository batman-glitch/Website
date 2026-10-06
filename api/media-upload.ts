import { handleUpload, type HandleUploadBody } from '@vercel/blob/client';

const imageTypes = ['image/jpeg', 'image/png', 'image/webp'];
const audioTypes = ['audio/mpeg', 'audio/mp4', 'audio/aac', 'audio/wav', 'audio/x-wav', 'audio/flac', 'audio/ogg'];
const imageExts = new Set(['.jpg', '.jpeg', '.png', '.webp']);
const audioExts = new Set(['.mp3', '.m4a', '.aac', '.wav', '.flac', '.ogg']);

async function requireAdmin(request: Request) {
  const origin = request.headers.get('origin');
  const host = request.headers.get('host');
  if (!origin || !host || new URL(origin).host.toLowerCase() !== host.toLowerCase()) {
    throw new Error('This upload request could not be verified. Refresh and sign in again.');
  }
  const result = await fetch(new URL('/api/auth/media-authorize/', origin), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Cookie': request.headers.get('cookie') || '', 'X-CSRFToken': request.headers.get('x-csrf-token') || '', 'Origin': origin },
    body: '{}',
  });
  if (!result.ok) throw new Error('Your secure session could not authorize this upload. Sign in again.');
}

export async function POST(request: Request) {
  try {
    if (!process.env.BLOB_READ_WRITE_TOKEN) {
      return Response.json({ error: 'Media storage is not ready. Contact the site administrator.' }, { status: 503, headers: { 'Cache-Control': 'no-store' } });
    }
    const body = (await request.json()) as HandleUploadBody;
    const result = await handleUpload({
      body,
      request,
      onBeforeGenerateToken: async (pathname, clientPayload) => {
        await requireAdmin(request);
        let parsedPayload: { kind?: unknown };
        try { parsedPayload = JSON.parse(clientPayload || '{}'); } catch { throw new Error('This upload request could not be verified.'); }
        const kind = parsedPayload && typeof parsedPayload === 'object' ? parsedPayload.kind : '';
        const filename = pathname.split('/').pop() || '';
        if (!filename || filename.includes('..') || filename.length > 140) throw new Error('Choose a shorter file name.');
        const extension = filename.slice(filename.lastIndexOf('.')).toLowerCase();
        if (kind === 'cover' && imageExts.has(extension)) {
          return { allowedContentTypes: imageTypes, maximumSizeInBytes: 12_000_000, addRandomSuffix: true, cacheControlMaxAge: 60 * 60 * 24 * 30 };
        }
        if (kind === 'audio' && audioExts.has(extension)) {
          return { allowedContentTypes: audioTypes, maximumSizeInBytes: 250_000_000, addRandomSuffix: true, cacheControlMaxAge: 60 * 60 * 24 * 30 };
        }
        throw new Error('That file type is not supported for this upload.');
      },
    });
    return Response.json(result, { headers: { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' } });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Could not prepare this upload.';
    const status = message.includes('session') || message.includes('sign in') ? 401 : 400;
    return Response.json({ error: message }, { status, headers: { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' } });
  }
}

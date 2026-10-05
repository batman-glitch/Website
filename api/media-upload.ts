import { createHash, timingSafeEqual } from 'node:crypto';
import { neon } from '@neondatabase/serverless';
import { handleUpload, type HandleUploadBody } from '@vercel/blob/client';

const sessionCookie = '__Host-blessson-session';
const csrfCookie = '__Host-blessson-csrf';
const imageTypes = ['image/jpeg', 'image/png', 'image/webp'];
const audioTypes = ['audio/mpeg', 'audio/mp4', 'audio/aac', 'audio/wav', 'audio/x-wav', 'audio/flac', 'audio/ogg'];
const imageExts = new Set(['.jpg', '.jpeg', '.png', '.webp']);
const audioExts = new Set(['.mp3', '.m4a', '.aac', '.wav', '.flac', '.ogg']);

function cookies(header: string | null) {
  const values: Record<string, string> = {};
  for (const part of (header || '').split(';')) {
    const divider = part.indexOf('=');
    if (divider < 0) continue;
    values[part.slice(0, divider).trim()] = part.slice(divider + 1).trim();
  }
  return values;
}

function sha256(value: string) {
  return createHash('sha256').update(value, 'utf8').digest('hex');
}

function equalHex(left: string, right: string) {
  if (!/^[0-9a-f]{64}$/i.test(left) || !/^[0-9a-f]{64}$/i.test(right)) return false;
  return timingSafeEqual(Buffer.from(left, 'hex'), Buffer.from(right, 'hex'));
}

async function requireAdmin(request: Request) {
  const origin = request.headers.get('origin');
  const host = request.headers.get('host');
  if (!origin || !host || new URL(origin).host.toLowerCase() !== host.toLowerCase()) {
    throw new Error('This upload request could not be verified. Refresh the page and sign in again.');
  }
  const cookie = cookies(request.headers.get('cookie'));
  const rawSession = cookie[sessionCookie] || '';
  const csrf = cookie[csrfCookie] || '';
  const suppliedCsrf = request.headers.get('x-csrf-token') || '';
  if (!rawSession || rawSession.length > 160 || !csrf || !suppliedCsrf || csrf !== suppliedCsrf) {
    throw new Error('Your session expired. Sign in again.');
  }
  const connectionString = process.env.DATABASE_URL;
  if (!connectionString) throw new Error('The secure database is not configured.');
  const sql = neon(connectionString);
  const rows = await sql`
    SELECT s.csrf_hash
    FROM admin_sessions s
    JOIN admin_users u ON u.id = s.user_id
    WHERE s.token_hash = ${sha256(rawSession)}
      AND s.expires_at > ${new Date().toISOString()}
      AND u.must_change_password = 0
  `;
  const row = rows[0];
  if (!row || !equalHex(String(row.csrf_hash), sha256(csrf)) || !equalHex(String(row.csrf_hash), sha256(suppliedCsrf))) {
    throw new Error('Your session expired. Sign in again.');
  }
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

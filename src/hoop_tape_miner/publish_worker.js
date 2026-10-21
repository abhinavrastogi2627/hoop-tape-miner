// Cloudflare Worker in front of the published site (hoop-tape-miner publish --deploy).
// Static assets answer a Range request with the whole file (200), but Safari / iOS WeChat only play
// <video> and seek <audio> when the server returns 206 Partial Content, so ranges are cut here.
// Every response also gets the security headers below; only GET / HEAD of plain paths reach the assets.

// Report pages: inline style and script (each published page also pins its own script by hash in a CSP meta
// tag), Google Fonts, images inlined as data: URIs, audio and clips from the site itself.
const CSP = [
  "default-src 'none'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  "font-src https://fonts.gstatic.com",
  "img-src 'self' data:",
  "media-src 'self' data:",
  "base-uri 'none'",
  "form-action 'none'",
  "frame-ancestors 'none'",
].join("; ");
const SECURITY = {
  "Content-Security-Policy": CSP,
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
  "X-Robots-Tag": "noindex, nofollow",
  "X-Frame-Options": "DENY",
};

function secure(response) {
  const out = new Response(response.body, response);  // asset responses are immutable; copy to set headers
  for (const [k, v] of Object.entries(SECURITY)) out.headers.set(k, v);
  return out;
}

function plain(status, text) {
  return new Response(text, { status, headers: { "Content-Type": "text/plain; charset=utf-8" } });
}

// Encoded slashes, backslashes, dot segments or NUL in the path: never a real asset, refuse them outright.
function badPath(url) {
  const raw = new URL(url).pathname;
  if (/%2f|%5c|%00|\\/i.test(raw)) return true;
  let path;
  try { path = decodeURIComponent(raw); } catch { return true; }
  return path.split("/").some((seg) => seg === ".." || seg === ".");
}

async function serve(request, env) {
  if (request.method !== "GET" && request.method !== "HEAD") {
    const r = plain(405, "method not allowed");
    r.headers.set("Allow", "GET, HEAD");
    return r;
  }
  if (badPath(request.url)) return plain(404, "not found");
  const range = request.headers.get("Range");
  if (!range || request.method !== "GET") return env.ASSETS.fetch(request);
  const headers = new Headers(request.headers);
  headers.delete("Range");
  headers.delete("If-Range");
  const full = await env.ASSETS.fetch(new Request(request.url, { headers }));
  if (full.status !== 200 || full.headers.has("Content-Encoding")) return full;
  const buf = await full.arrayBuffer(), size = buf.byteLength;
  const out = new Headers(full.headers);
  out.set("Accept-Ranges", "bytes");
  const m = /^bytes=(\d*)-(\d*)$/.exec(range.trim());
  if (!m || (!m[1] && !m[2])) return new Response(buf, { status: 200, headers: out });  // multi-range: whole file
  let start, end;
  if (m[1]) {
    start = Number(m[1]);
    end = m[2] ? Math.min(Number(m[2]), size - 1) : size - 1;
  } else {
    start = Math.max(size - Number(m[2]), 0);
    end = size - 1;
  }
  if (start >= size || start > end) {
    out.set("Content-Range", `bytes */${size}`);
    out.delete("Content-Length");
    return new Response(null, { status: 416, headers: out });
  }
  out.set("Content-Range", `bytes ${start}-${end}/${size}`);
  out.set("Content-Length", String(end - start + 1));
  return new Response(buf.slice(start, end + 1), { status: 206, headers: out });
}

export default {
  async fetch(request, env) {
    return secure(await serve(request, env));
  },
};

// Cloudflare Worker in front of the published site (hoop-tape-miner publish --deploy).
// Static assets answer a Range request with the whole file (200), but Safari / iOS WeChat only play
// <video> and seek <audio> when the server returns 206 Partial Content, so ranges are cut here.
export default {
  async fetch(request, env) {
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
  },
};

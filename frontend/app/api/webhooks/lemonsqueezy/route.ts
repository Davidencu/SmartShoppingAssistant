export async function POST(request: Request) {
  const backend = process.env.BACKEND_URL ?? "http://localhost:8000";
  const body = await request.arrayBuffer();
  const signature = request.headers.get("X-Signature") ?? "";

  const res = await fetch(`${backend}/webhooks/lemonsqueezy`, {
    method: "POST",
    body,
    headers: {
      "Content-Type": "application/json",
      "X-Signature": signature,
    },
  });

  return new Response(null, { status: res.status });
}

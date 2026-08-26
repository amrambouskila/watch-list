import { ApiError } from "./ApiError";

interface ErrorBody {
  error?: string;
  message?: string;
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body !== undefined) headers.set("Content-Type", "application/json");

  const response = await fetch(path, { ...init, headers });

  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as ErrorBody;
    throw new ApiError(
      response.status,
      body.error ?? "RequestFailed",
      body.message ?? `The server refused that change (${response.status}).`,
    );
  }

  return (await response.json()) as T;
}

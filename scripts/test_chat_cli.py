import argparse
import json
import uuid

import httpx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI Helper 終端對話測試工具")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="AI Helper 服務位址")
    parser.add_argument("--user-id", type=int, default=3, help="開發模式使用者 ID")
    parser.add_argument("--pond-id", type=int, required=True, help="魚池 ID")
    parser.add_argument("--session-id", default=None, help="對話 Session ID，不傳會自動生成")
    parser.add_argument("--jwt", default="", help="正式模式可傳 Bearer Token")
    return parser.parse_args()


def parse_sse_line(raw_line: str, current_event: str | None) -> tuple[str | None, dict | None]:
    if raw_line.startswith("event: "):
        return raw_line[7:], None
    if raw_line.startswith("data: "):
        return current_event, json.loads(raw_line[6:])
    return current_event, None


def main() -> None:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    session_id = args.session_id or f"cli-{uuid.uuid4()}"
    headers = {"Content-Type": "application/json"}
    if args.jwt:
        headers["Authorization"] = f"Bearer {args.jwt}"

    print(f"已連線到 {base_url}")
    print(f"session_id = {session_id}")
    print("輸入 exit 可結束對話。")

    with httpx.Client(timeout=None) as client:
        while True:
            message = input("\n你: ").strip()
            if not message:
                continue
            if message.lower() in {"exit", "quit"}:
                print("結束對話。")
                break

            payload = {
                "user_id": args.user_id,
                "pond_id": args.pond_id,
                "session_id": session_id,
                "message": message,
            }

            print("AI: ", end="", flush=True)
            current_event = None
            printed_source = False

            with client.stream("POST", f"{base_url}/api/ai/chat/stream", headers=headers, json=payload) as response:
                response.raise_for_status()

                for raw_line in response.iter_lines():
                    if not raw_line:
                        continue

                    if isinstance(raw_line, bytes):
                        raw_line = raw_line.decode("utf-8", errors="replace")

                    current_event, data = parse_sse_line(raw_line, current_event)
                    if data is None:
                        continue

                    if current_event == "source" and not printed_source:
                        citations = data.get("citations", [])
                        pond_name = data.get("pond_name")
                        print(f"\n[來源] pond={pond_name} citations={len(citations)}")
                        for item in citations[:5]:
                            print(f"- [{item.get('reference_no')}] {item.get('title')}")
                        print("AI: ", end="", flush=True)
                        printed_source = True
                    elif current_event == "token":
                        print(data.get("content", ""), end="", flush=True)
                    elif current_event == "error":
                        print(f"\n[錯誤] {data.get('message')}", flush=True)
                    elif current_event == "done":
                        print("", flush=True)
                        break


if __name__ == "__main__":
    main()

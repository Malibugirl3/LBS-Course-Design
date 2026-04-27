import json
import threading
import time

import requests

BASE_URL = "http://127.0.0.1:3000"


def start_listener(competition_id, team_id, member_id):
    def worker():
        url = f"{BASE_URL}/competitions/{competition_id}/stream"
        try:
            with requests.get(
                url,
                params={"teamId": team_id, "memberId": member_id},
                stream=True,
                timeout=60,
            ) as response:
                response.raise_for_status()
                current_event = None

                for raw_line in response.iter_lines(decode_unicode=True):
                    if not raw_line:
                        continue
                    if raw_line.startswith(":"):
                        continue
                    if raw_line.startswith("event:"):
                        current_event = raw_line.split(":", 1)[1].strip()
                    elif raw_line.startswith("data:"):
                        payload = json.loads(raw_line.split(":", 1)[1].strip())
                        print(f"[通知] {team_id}/{member_id} <- {current_event}: {payload}")
                        if current_event == "competition-finished":
                            break
        except Exception as exc:
            print(f"[通知异常] {team_id}/{member_id}: {exc}")

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return thread


def post_json(path, payload):
    response = requests.post(f"{BASE_URL}{path}", json=payload, timeout=10)
    data = response.json()
    print(f"POST {path} -> {response.status_code} {data}")
    return data


def get_json(path):
    response = requests.get(f"{BASE_URL}{path}", timeout=10)
    data = response.json()
    print(f"GET  {path} -> {response.status_code} {data}")
    return data


def main():
    comp = post_json("/competitions", {"x": 10, "y": 10})
    competition_id = comp["competitionId"]

    post_json(f"/competitions/{competition_id}/teams", {"teamId": "Alpha"})
    post_json(f"/competitions/{competition_id}/teams", {"teamId": "Bravo"})

    listeners = [
        start_listener(competition_id, "Alpha", "M1"),
        start_listener(competition_id, "Alpha", "M2"),
        start_listener(competition_id, "Alpha", "M3"),
        start_listener(competition_id, "Bravo", "N1"),
    ]

    time.sleep(1)

    reports = [
        {"competitionId": competition_id, "teamId": "Bravo", "memberId": "N1", "x": 2, "y": 3},
        {"competitionId": competition_id, "teamId": "Alpha", "memberId": "M1", "x": 10.4, "y": 10.2},
        {"competitionId": competition_id, "teamId": "Alpha", "memberId": "M2", "x": 9.2, "y": 10.6},
        {"competitionId": competition_id, "teamId": "Alpha", "memberId": "M3", "x": 10.1, "y": 9.3},
        {"competitionId": competition_id, "teamId": "Bravo", "memberId": "N1", "x": 10.0, "y": 10.0},
    ]

    for payload in reports:
        result = post_json("/reports", payload)
        print(f"[上报结果] {payload['teamId']}/{payload['memberId']} -> {result}")
        time.sleep(0.6)

    get_json(f"/competitions/{competition_id}/target")
    get_json(f"/competitions/{competition_id}/status")

    time.sleep(2)
    print(f"监听线程数: {len(listeners)}")
    print("测试结束。")


if __name__ == "__main__":
    main()

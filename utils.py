import httpx
from time import sleep
from random import randint


def get_user_agent_and_cookies(
    url: str = None, tries: int = 3
) -> tuple[str | None, dict]:
    if tries <= 0:
        return None, {}
    try:
        with httpx.Client() as session:
            response = session.post(
                "http://localhost:8000/bypass-cloudflare",
                headers={"Content-Type": "application/json"},
                json={"url": f"{url}"},
            )
            response_json = response.json()
            print(response_json)
            return response_json["user_agent"], response_json["cookies"]
    except Exception as e:
        print(f"{url}\nError getting user agent and cookies on try {tries}: {e}")
        sleep(randint(1, 3))
        return get_user_agent_and_cookies(url=url, tries=tries - 1)

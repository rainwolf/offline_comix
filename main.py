import json
import asyncio
import random
import aiohttp
import docker
import bs4
import re
import requests
import os
import glob
from pandas.io.clipboard import clipboard_get
from time import sleep
from random import randint
from urllib.parse import urlsplit


BASE_URL = "https://comix.to"
# get content from clipboard
clipboard = clipboard_get()
limit = 5


def get_user_agent_and_cookies(
    url: str = BASE_URL, tries: int = 3
) -> tuple[str | None, dict]:
    if tries <= 0:
        return None, {}
    try:
        with requests.Session() as session:
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


async def download(
    url: str,
    i: int,
    total_images: int,
    session: aiohttp.ClientSession,
    chapter_number: str,
    comic_title: str,
    chapter_title: str,
    total_chapters: int,
    semaphore: asyncio.Semaphore,
    cookies: dict,
    headers: dict,
    retry_count: int = 0,
):
    # if retry_count > 10:
    if retry_count > 0:
        print(
            f"Failed to download image {i} of {total_images} in chapter {chapter_number} of {total_chapters} after multiple retries."
        )
        return

    file_path = (
        f"../{comic_title}/{chapter_number} {comic_title} - {chapter_title} - {i:05}"
    )
    if len(file_path) > 250:
        file_path = f"../{comic_title}/{chapter_number} - {chapter_title} - {i:05}"
    file_list = glob.glob(f"{file_path}.*")
    if file_list and len(file_list) > 0 and os.path.getsize(file_list[0]) > 8000:
        print(
            f"Chapter: {chapter_number} of {total_chapters}: Image {i} of {total_images} already exists, skipping download..."
        )
        return
    try:
        await asyncio.sleep(random.uniform(0.2, 2.5))
        async with (
            semaphore,
            session.get(url, headers=headers, cookies=cookies) as response,
        ):
            file = await response.read()
            if len(file) < 8000:
                raise Exception(f"File size too small, retrying... {retry_count=}")
            ext = url[-5:]
            if ext[0] != ".":
                ext = ext[1:]
            file_path = f"{file_path}{ext}"
            with open(
                file_path,
                "wb",
            ) as f:
                f.write(file)
            print(
                f"Chapter: {chapter_number} of {total_chapters}: Finished downloading image {i} of {total_images}..."
            )
    except Exception as e:
        print(
            f"Error downloading image {i} of {total_images} in chapter {c} of {total_chapters}: {e}, retrying..."
        )
        await asyncio.sleep(random.randint(1, 3))
        await download(
            url,
            i,
            total_images,
            session,
            chapter_number,
            comic_title,
            chapter_title,
            total_chapters,
            semaphore,
            cookies,
            headers,
            retry_count=retry_count + 1,
        )


async def download_chapter(
    chapter_url: str,
    chapter_number: str,
    comic_title: str,
    total_chapters: int,
    headers: dict,
    cookies: dict,
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
):
    async with session.get(chapter_url, headers=headers, cookies=cookies) as response:
        chapter_page_source = await response.text()
    soup = bs4.BeautifulSoup(chapter_page_source, "html.parser")
    chapter_title = soup.find("title").text
    print(
        f"Downloading chapter {chapter_number} of {total_chapters}: {chapter_title}..."
    )
    image_urls = re.findall(r"(https?://[^\"]+/\d+\.[a-z]+)\\\"", chapter_page_source)

    def f7(seq):
        seen = set()
        seen_add = seen.add
        return [x for x in seq if not (x in seen or seen_add(x))]

    image_urls = f7(image_urls)
    image_urls = sorted(image_urls, key=lambda x: x.split("/")[-1])
    tasks = []
    i = 0
    total = len(image_urls)

    for img_url in image_urls:
        i += 1
        tasks.append(
            download(
                img_url,
                i,
                total,
                session,
                chapter_number,
                comic_title,
                chapter_title,
                total_chapters,
                semaphore,
                cookies,
                headers,
            )
        )
    await asyncio.gather(*tasks)


async def get_chapter_ids(
    comic_id: str, headers: dict, cookies: dict, session: aiohttp.ClientSession
) -> dict[str, str]:
    page = 1
    chapters = {}
    while True:
        chapters_url = f"https://comix.to/api/v2/manga/{comic_id}/chapters?limit=20&page={page}&order[number]=asc"
        async with session.get(
            chapters_url, headers=headers, cookies=cookies
        ) as response:
            chapters_source = await response.text()
        chapters_data = json.loads(chapters_source)["result"]
        for item in chapters_data["items"]:
            if item["scanlation_group"] is None or chapters.get(item["number"]) is None:
                chapters[item["number"]] = item["chapter_id"]
        if (
            chapters_data["pagination"]["current_page"]
            >= chapters_data["pagination"]["last_page"]
        ):
            break
        page += 1
    return chapters


async def main():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/102.0.0.0 Safari/537.36"
    }
    clipboard = clipboard_get()
    prefix = f"{BASE_URL}/title/"
    if not clipboard.startswith(prefix):
        print(f"Clipboard content does not start with {prefix}, exiting.")
        exit(1)
    comic_id_regex = re.compile(rf"{prefix}(\d+)-")
    match = comic_id_regex.match(clipboard)
    if not match:
        print("Could not extract comic ID from clipboard content, exiting.")
        exit(1)
    comic_id = match.group(1)
    user_agent, cookies = get_user_agent_and_cookies(url=clipboard)
    # cookies.update({"nsfw": "2"})
    if user_agent is None:
        comic_source = requests.get(clipboard, headers=headers, cookies=cookies).text
    else:
        headers = {"User-Agent": user_agent}
        comic_source = requests.get(clipboard, headers=headers, cookies=cookies).text

    headers["referer"] = BASE_URL

    print(f"Fetching comic information from {clipboard}...")
    chapter_ids_dict = await get_chapter_ids(
        comic_id, headers, cookies, aiohttp.ClientSession()
    )

    soup = bs4.BeautifulSoup(comic_source, "html.parser")
    comic_title = soup.find("title").text.replace(" - Manga", "")
    # make folder with title
    os.makedirs(f"../{comic_title}", exist_ok=True)
    print(f"Downloading {comic_title}...")
    print(f"Found {len(chapter_ids_dict)} chapters to download.")

    semaphore = asyncio.BoundedSemaphore(limit)
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(limit=limit)
    ) as session:
        tasks = []
        i = 0
        total_chapters = len(chapter_ids_dict)
        for chapter_number, chapter_id in chapter_ids_dict.items():
            tasks.append(
                download_chapter(
                    f"{clipboard}/{chapter_id}-chapter-{chapter_number}",
                    f"{float(chapter_number):0>5.1f}",
                    comic_title,
                    total_chapters,
                    headers,
                    cookies,
                    session,
                    semaphore,
                )
            )
        await asyncio.gather(*tasks)
    if len(os.listdir(f"../{comic_title}")) == 0:
        os.rmdir(f"../{comic_title}")
        print(f"No chapters were downloaded for {comic_title}, folder removed.")
    else:
        print(f"Finished downloading {comic_title}.")


if __name__ == "__main__":
    with asyncio.Runner() as runner:
        runner.run(main())
    exit(0)
    container = None
    try:
        client = docker.DockerClient(base_url="unix://var/run/docker.sock")
        client.images.pull("frederikuni/docker-cloudflare-bypasser:latest")
        container = client.containers.run(
            "frederikuni/docker-cloudflare-bypasser:latest",
            detach=True,
            ports={"8000/tcp": 8000},
        )
        with asyncio.Runner() as runner:
            runner.run(main())
    finally:
        container.stop()
        container.remove()

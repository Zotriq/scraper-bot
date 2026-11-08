import hashlib
import os
import re
from urllib.parse import parse_qsl, urljoin, urlparse
from bs4 import BeautifulSoup
import requests
import urllib3
from concurrent.futures import ThreadPoolExecutor, as_completed

# Disable SSL warnings for self-signed or unverified enterprise certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_DOWNLOAD_DIR = "./downloads"
os.makedirs(BASE_DOWNLOAD_DIR, exist_ok=True)


def sanitize_folder_name(name: str) -> str:
    """Sanitizes strings to create valid OS folder/file names."""
    return re.sub(r'[\\/*?:"<>|]', "_", name).strip()


def sanitize_and_generate_dynamic_folder(raw_url: str) -> tuple:
    """
    Cleans raw URLs and generates a guaranteed unique workspace directory path.
    Uses domain, path, query parameters, and an MD5 hash to prevent folder collisions.
    """
    if not raw_url or not isinstance(raw_url, str):
        return None, None

    sanitized_url = raw_url.strip().replace("\n", "").replace("\r", "")
    parsed = urlparse(sanitized_url)

    # Build unique slug from domain + path + query
    raw_slug = f"{parsed.netloc}_{parsed.path}_{parsed.query}"
    clean_slug = re.sub(r"[^a-zA-Z0-9_\-]", "_", raw_slug)
    clean_slug = re.sub(r"_+", "_", clean_slug).strip("_")

    # Generate a short 6-char hash of the full URL to guarantee uniqueness
    url_hash = hashlib.md5(sanitized_url.encode("utf-8")).hexdigest()[:6]

    # Clean up edge cases like index pages or overly short slugs
    if not clean_slug or len(clean_slug) < 10 or "index" in clean_slug.lower():
        final_folder_name = f"{clean_slug[:60]}_{url_hash}" if clean_slug else f"site_{url_hash}"
    else:
        final_folder_name = f"{clean_slug[:80]}_{url_hash}"

    final_folder_name = sanitize_folder_name(final_folder_name)
    unique_target_path = os.path.normpath(
        os.path.join(BASE_DOWNLOAD_DIR, final_folder_name)
    )
    
    return sanitized_url, unique_target_path


def download_single_asset(
    asset_route: str, session_workspace: str, headers: dict
):
    """Worker for downloading discovered sub-assets into the target workspace directory."""
    try:
        with requests.get(
            asset_route, headers=headers, stream=True, timeout=10, verify=False
        ) as sub_res:
            sub_type = sub_res.headers.get("Content-Type", "").lower()

            if "text/html" in sub_type or not sub_res.ok:
                return

            sub_disp = sub_res.headers.get("Content-Disposition", "")
            if "filename=" in sub_disp:
                matches = re.findall(r'filename=["\']?(.*?)["\']?$', sub_disp)
                sub_filename = matches[0] if matches else None
            else:
                sub_filename = os.path.basename(urlparse(asset_route).path)

            if (
                not sub_filename
                or "." not in sub_filename
                or sub_filename.endswith(".php")
            ):
                sub_query = dict(parse_qsl(urlparse(asset_route).query))
                asset_id = sub_query.get("id") or "file_record"
                ext = (
                    ".pdf"
                    if "pdf" in sub_type
                    else ".xlsx"
                    if "excel" in sub_type
                    else ".docx"
                )
                sub_filename = f"extracted_asset_{asset_id}{ext}"

            sub_filename = sanitize_folder_name(sub_filename)
            file_path = os.path.join(session_workspace, sub_filename)

            with open(file_path, "wb") as f_sub:
                for chunk in sub_res.iter_content(chunk_size=32768):
                    f_sub.write(chunk)
            print(f"      ✓ Asset Saved: {sub_filename}")
    except Exception:
        pass


def dynamic_session_extractor(
    target_url: str, session_workspace: str
):
    """
    Extracts webpage text content into a uniquely named .txt file (matching the workspace directory name)
    and downloads all linked documents (PDFs, Excels, Docs, etc.) into the same folder.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            " (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
    }

    # Always ensure destination directory exists
    os.makedirs(session_workspace, exist_ok=True)

    # Folder basename forms the exact title of the scraped text file inside it
    folder_basename = os.path.basename(os.path.normpath(session_workspace))

    try:
        with requests.get(
            target_url, headers=headers, stream=True, timeout=15, verify=False
        ) as response:
            if response.status_code == 404:
                print(f"   ⚠ 404 Server Status for {target_url}")
                return
            response.raise_for_status()

            content_type = response.headers.get("Content-Type", "").lower()
            content_disposition = response.headers.get(
                "Content-Disposition", ""
            )

            is_binary = any(
                t in content_type
                for t in [
                    "pdf",
                    "spreadsheet",
                    "excel",
                    "word",
                    "octet-stream",
                    "zip",
                ]
            )
            is_forced = "filename=" in content_disposition

            # Direct downloadable binary asset
            if is_binary or is_forced:
                if "text/html" in content_type:
                    return

                if is_forced:
                    filename = re.findall(
                        r'filename=["\']?(.*?)["\']?$', content_disposition
                    )[0]
                else:
                    filename = os.path.basename(urlparse(target_url).path)

                if (
                    not filename
                    or "." not in filename
                    or filename.endswith(".php")
                ):
                    ext = (
                        ".pdf"
                        if "pdf" in content_type
                        else ".xlsx"
                        if "excel" in content_type
                        else ".docx"
                    )
                    filename = f"document_download{ext}"

                filename = sanitize_folder_name(filename)
                with open(
                    os.path.join(session_workspace, filename), "wb"
                ) as f:
                    for chunk in response.iter_content(chunk_size=32768):
                        f.write(chunk)
                print(f"   ✓ Extracted direct asset file: {filename}")

            # HTML Parsing Block
            else:
                try:
                    soup = BeautifulSoup(response.text, "lxml")
                except Exception:
                    soup = BeautifulSoup(response.text, "html.parser")

                # Decompose structural noise elements
                for element in soup(
                    ["script", "style", "nav", "footer", "header", "aside"]
                ):
                    element.decompose()

                structured_blocks = []
                tags_to_extract = [
                    "h1", "h2", "h3", "h4", "h5", "h6",
                    "p", "ul", "ol", "table", "form"
                ]
                all_elements = soup.find_all(tags_to_extract)

                for element in all_elements:
                    if element.find_parent(["table", "form", "ul", "ol"]):
                        continue

                    if element.name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                        text = element.get_text(strip=True)
                        if text:
                            structured_blocks.append(f"\n{text}\n")

                    elif element.name == "p":
                        text = element.get_text(strip=True)
                        if text:
                            structured_blocks.append(text)

                    elif element.name in ["ul", "ol"]:
                        list_items = [
                            f"- {li.get_text(strip=True)}"
                            for li in element.find_all("li", recursive=False)
                            if li.get_text(strip=True)
                        ]
                        if list_items:
                            structured_blocks.append(
                                "\n" + "\n".join(list_items) + "\n"
                            )

                    elif element.name == "table":
                        headers_list = []
                        columns_data = {}
                        thead = element.find("thead")
                        header_source = thead if thead else element
                        first_tr = header_source.find("tr")

                        if first_tr:
                            for th in first_tr.find_all(["th", "td"]):
                                header_text = th.get_text(strip=True)
                                headers_list.append(header_text)
                                columns_data[header_text] = []

                        tbody = element.find("tbody")
                        row_source = tbody if tbody else element
                        all_trs = row_source.find_all("tr")
                        start_idx = (
                            1 if not thead and first_tr in all_trs else 0
                        )

                        for tr in all_trs[start_idx:]:
                            for idx, td in enumerate(
                                tr.find_all(["td", "th"])
                            ):
                                if idx < len(headers_list):
                                    cell_strings = [
                                        s for s in td.stripped_strings
                                    ]
                                    cell_text = (
                                        " ".join(cell_strings)
                                        if cell_strings
                                        else "-"
                                    )
                                    columns_data[headers_list[idx]].append(
                                        cell_text
                                    )

                        table_output = [
                            f"{h}: {', '.join(columns_data[h])}"
                            for h in headers_list
                        ]
                        if table_output:
                            structured_blocks.append(
                                "\n" + "\n".join(table_output) + "\n"
                            )

                    elif element.name == "form":
                        form_elements = []
                        for field in element.find_all(
                            ["label", "input", "select", "textarea"]
                        ):
                            if field.name == "label":
                                form_elements.append(
                                    f"Label: {field.get_text(strip=True)}"
                                )
                            elif field.name in ["input", "select", "textarea"]:
                                form_elements.append(
                                    f"  -> [{field.get('type', field.name).upper()}] Name: {field.get('name', 'unnamed')}"
                                )
                        if form_elements:
                            structured_blocks.append(
                                "\n[FORM FIELD LAYOUT]\n"
                                + "\n".join(form_elements)
                                + "\n[FORM END]\n"
                            )

                final_page_text = "\n".join(structured_blocks).strip()

                # Save text content into <folder_basename>.txt inside session_workspace
                text_filename = f"{folder_basename}.txt"
                text_filepath = os.path.join(session_workspace, text_filename)

                with open(text_filepath, "w", encoding="utf-8") as text_file:
                    text_file.write(f"Source URL: {target_url}\n")
                    text_file.write("=" * 80 + "\n\n")
                    text_file.write(final_page_text)

                print(f"   ✓ Extracted text -> {text_filename}")

                # Inner Parallel Execution for sub-asset extraction
                anchors = soup.find_all("a", href=True)
                doc_extensions = re.compile(
                    r"\.(pdf|xlsx|xls|docx|doc)(\?|$)", re.IGNORECASE
                )
                keyword_triggers = [
                    "download",
                    "attachment",
                    "view-service",
                    "viewfile",
                    "form",
                    "document",
                ]

                valid_links = set()
                for link in anchors:
                    href = link["href"]
                    text = link.get_text(strip=True).lower()

                    if doc_extensions.search(href) or any(
                        k in href.lower() or k in text for k in keyword_triggers
                    ):
                        if not any(
                            term in href.lower()
                            for term in [
                                "login",
                                "logout",
                                "javascript:",
                                "facebook",
                                "twitter",
                            ]
                        ):
                            valid_links.add(urljoin(target_url, href))

                if valid_links:
                    with ThreadPoolExecutor(max_workers=5) as inner_executor:
                        for asset_route in valid_links:
                            inner_executor.submit(
                                download_single_asset,
                                asset_route,
                                session_workspace,
                                headers,
                            )

    except Exception as e:
        print(f"   ✗ Connection Interrupted ({target_url}): {e}")


def process_all_urls_in_parallel(url_list: list, max_concurrent_pages: int = 15):
    """
    Main batch processing launcher function. Run this to execute top-level parallel scraping.
    """
    work_units = []
    for raw_url in url_list:
        clean_url, session_workspace = sanitize_and_generate_dynamic_folder(raw_url)
        if clean_url:
            work_units.append((clean_url, session_workspace))

    total_tasks = len(work_units)
    print(f"🚀 Starting parallel extraction for {total_tasks} URLs with {max_concurrent_pages} parallel workers...\n")
    print("=" * 60)

    with ThreadPoolExecutor(max_workers=max_concurrent_pages) as executor:
        future_to_task = {
            executor.submit(dynamic_session_extractor, clean_url, session_workspace): (idx, clean_url, session_workspace)
            for idx, (clean_url, session_workspace) in enumerate(work_units, start=1)
        }

        for future in as_completed(future_to_task):
            idx, clean_url, session_workspace = future_to_task[future]
            print(f"\n[{idx}/{total_tasks}] Container Workflow Completed")
            print(f"   ↳ Target URL: {clean_url}")
            print(f"   ↳ Destination Path: {session_workspace}")
            try:
                future.result()
            except Exception as e:
                print(f"   ↳ ✗ Execution Failed: {e}")

    print("\n" + "=" * 60 + "\n=== SYSTEM PIPELINE PROCESSING COMPLETE ===")
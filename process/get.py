"""
config_downloader.py
--------------------
从远程配置服务下载配置文件。
支持单文件下载、批量下载（通过远程 INI 清单）。
可在代码中直接定义 URL，也可由其他脚本调用并传入 URL。
"""

import os
import time
import configparser
import requests


# ============================================================
#  基础配置（按需修改）
# ============================================================

DOMAIN          = os.environ["DOMAIN"]           # 环境变量中的服务域名（无前缀）
BASE_URL        = f"https://{DOMAIN}"            # 自动补全前缀
ACCESS_KEY      = os.environ["ACCESS_KEY"]       # 环境变量中的访问密钥
DOWNLOAD_DIR    = "./code"                       # 本地下载根目录
MANIFEST_PATH   = "iptv/code/ini/script_urls.ini"      # INI 清单在存储中的路径
BATCH_INTERVAL  = 2.5                            # 批量下载间隔（秒）


# ============================================================
#  内部工具函数
# ============================================================

def _build_url(storage_path: str) -> str:
    """拼接完整的读取 URL（不对外暴露）。"""
    return f"{BASE_URL}/config/read_config/{storage_path}?token={ACCESS_KEY}"


def _fetch(storage_path: str) -> requests.Response:
    """向服务端发起请求获取配置内容（不打印 URL）。"""
    url = _build_url(storage_path)
    response = requests.post(url, timeout=15)
    response.raise_for_status()
    return response


def _save(content: str, rel_path: str, filename: str) -> str:
    """
    将内容保存到本地。
    本地目录结构与存储路径保持一致：DOWNLOAD_DIR / rel_path / filename
    """
    save_dir = os.path.join(DOWNLOAD_DIR, rel_path.replace("/", os.sep))
    os.makedirs(save_dir, exist_ok=True)
    filepath = os.path.join(save_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return filepath


# ============================================================
#  对外接口
# ============================================================

def download_file(storage_path: str = None, *, path: str = None, filename: str = None, verbose: bool = False) -> str:
    """
    下载单个配置文件。

    用法 A：直接传入存储路径字符串
        download_file("test/test1/000.yaml")

    用法 B：分别传入路径和文件名
        download_file(path="test/test1", filename="000.yaml")

    也可由其他脚本调用：
        from config_downloader import download_file
        download_file("some/path/file.yaml", verbose=True)

    返回：本地保存路径
    """
    if storage_path is None:
        if path is None or filename is None:
            raise ValueError("请提供 storage_path，或同时提供 path 和 filename。")
        storage_path = f"{path}/{filename}"
    else:
        parts    = storage_path.rsplit("/", 1)
        path     = parts[0] if len(parts) == 2 else ""
        filename = parts[-1]

    if verbose:
        print(f"[下载] {filename}  ←  {path}/")
    response = _fetch(storage_path)
    saved_to = _save(response.text, path, filename)
    if verbose:
        print(f"[完成] 已保存至 {saved_to}")
    return saved_to


def download_batch(manifest_storage_path: str = None, verbose: bool = False) -> list[str]:
    """
    批量下载：先获取远程 INI 清单，再逐项下载。

    manifest_storage_path：INI 清单在存储中的路径，默认使用代码顶部定义的 MANIFEST_PATH。
    也可由其他脚本传入：
        from config_downloader import download_batch
        download_batch("manifest/my_list", verbose=True)

    返回：所有成功下载的本地路径列表
    """
    target_path = manifest_storage_path or MANIFEST_PATH

    # ── 1. 拉取 INI 清单 ──
    if verbose:
        print("[索引] 正在获取下载清单...")
    response = _fetch(target_path)
    raw_ini  = response.text

    # ── 2. 解析 INI ──
    config = configparser.ConfigParser()
    config.read_string(raw_ini)

    sections = config.sections()
    if not sections:
        if verbose:
            print("[索引] 清单为空，无文件可下载。")
        return []

    total     = len(sections)
    saved     = []
    errors    = []   # 存储 (section, error_msg)

    if verbose:
        print(f"[索引] 共发现 {total} 个配置项，即将开始下载...\n")

    for idx, section in enumerate(sections, start=1):
        # 始终显示“正在下载”行（用户要求）
        print(f"[{idx}/{total}] 正在下载 [{section}]")

        storage_path = config.get(section, "Path",      fallback="").strip()
        filename     = config.get(section, "File_name", fallback="").strip()

        if not storage_path or not filename:
            msg = "缺少 Path 或 File_name"
            if verbose:
                print(f"  ✗ {msg}")
            else:
                print(f"[{idx}/{total}]下载失败。")
            errors.append((section, msg))
            continue

        try:
            local_path = download_file(storage_path=storage_path, filename=filename, verbose=verbose)
            saved.append(local_path)
            if not verbose:
                print(f"[{idx}/{total}]下载成功。")
        except requests.HTTPError as e:
            msg = f"HTTP {e.response.status_code}"
            if verbose:
                print(f"  ✗ {msg}")
            else:
                print(f"[{idx}/{total}]下载失败。")
            errors.append((section, msg))
        except requests.RequestException as e:
            msg = f"网络错误：{e}"
            if verbose:
                print(f"  ✗ {msg}")
            else:
                print(f"[{idx}/{total}]下载失败。")
            errors.append((section, msg))

        # ── 间隔等待（最后一个不等待，且 verbose 时才打印等待信息）──
        if idx < total:
            if verbose:
                print(f"  等待 {BATCH_INTERVAL} 秒...")
            time.sleep(BATCH_INTERVAL)

    # ── 3. 汇总（仅 verbose 模式）──
    if verbose:
        print(f"\n{'='*40}")
        print(f"下载完成：成功 {len(saved)} 个，失败 {len(errors)} 个。")
        if errors:
            err_sections = [e[0] for e in errors]
            print(f"失败项：{', '.join(err_sections)}")
        print(f"{'='*40}")

    return saved


# ============================================================
#  直接运行入口
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="远程配置下载工具")
    parser.add_argument("--debug", action="store_true", help="显示详细调试信息（文件路径、等待时间等）")
    sub = parser.add_subparsers(dest="command")

    # 子命令：单文件
    p_single = sub.add_parser("single", help="下载单个配置文件")
    p_single.add_argument("storage_path", help="存储路径，例如 test/test1/000.yaml")

    # 子命令：批量
    p_batch = sub.add_parser("batch", help="批量下载（从远程 INI 清单）")
    p_batch.add_argument(
        "--manifest", default=None,
        help=f"INI 清单的存储路径（默认：{MANIFEST_PATH}）"
    )

    args = parser.parse_args()

    if args.command == "single":
        download_file(args.storage_path, verbose=args.debug)
    elif args.command == "batch":
        download_batch(args.manifest, verbose=args.debug)
    else:
        parser.print_help()

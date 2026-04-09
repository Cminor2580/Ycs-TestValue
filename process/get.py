"""
config_downloader.py
--------------------
从 Cloudflare Worker 下载配置文件。
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

BASE_URL        = "https://config.243672.xyz"   # Worker 域名（不含末尾斜杠）
TOKEN           = "your_token_here"              # 鉴权 Token
DOWNLOAD_DIR    = "./downloads"                  # 本地下载根目录
MANIFEST_PATH   = "manifest/download_list"      # INI 清单在 KV 中的路径
BATCH_INTERVAL  = 2.5                            # 批量下载间隔（秒）


# ============================================================
#  内部工具函数
# ============================================================

def _build_url(kv_path: str) -> str:
    """拼接完整的读取 URL（不对外暴露）。"""
    return f"{BASE_URL}/config/read_config/{kv_path}?token={TOKEN}"


def _post(kv_path: str) -> requests.Response:
    """向 Worker 发起 POST 请求（不打印 URL）。"""
    url = _build_url(kv_path)
    response = requests.post(url, timeout=15)
    response.raise_for_status()
    return response


def _save(content: str, rel_path: str, filename: str) -> str:
    """
    将内容保存到本地。
    本地目录结构与 KV 路径保持一致：DOWNLOAD_DIR / rel_path / filename
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

def download_file(kv_path: str = None, *, path: str = None, filename: str = None) -> str:
    """
    下载单个配置文件。

    用法 A：直接传入 KV 路径字符串
        download_file("test/test1/000.yaml")

    用法 B：分别传入路径和文件名
        download_file(path="test/test1", filename="000.yaml")

    也可由其他脚本调用：
        from config_downloader import download_file
        download_file("some/path/file.yaml")

    返回：本地保存路径
    """
    if kv_path is None:
        if path is None or filename is None:
            raise ValueError("请提供 kv_path，或同时提供 path 和 filename。")
        kv_path = f"{path}/{filename}"
    else:
        parts    = kv_path.rsplit("/", 1)
        path     = parts[0] if len(parts) == 2 else ""
        filename = parts[-1]

    print(f"[下载] {filename}  ←  {path}/")
    response = _post(kv_path)
    saved_to = _save(response.text, path, filename)
    print(f"[完成] 已保存至 {saved_to}")
    return saved_to


def download_batch(manifest_kv_path: str = None) -> list[str]:
    """
    批量下载：先获取远程 INI 清单，再逐项下载。

    manifest_kv_path：INI 清单在 KV 中的路径，默认使用代码顶部定义的 MANIFEST_PATH。
    也可由其他脚本传入：
        from config_downloader import download_batch
        download_batch("manifest/my_list")

    返回：所有成功下载的本地路径列表
    """
    target_path = manifest_kv_path or MANIFEST_PATH

    # ── 1. 拉取 INI 清单 ──
    print("[清单] 正在获取下载清单...")
    response = _post(target_path)
    raw_ini  = response.text

    # ── 2. 解析 INI ──
    config = configparser.ConfigParser()
    config.read_string(raw_ini)

    sections = config.sections()
    if not sections:
        print("[清单] 清单为空，无文件可下载。")
        return []

    total     = len(sections)
    saved     = []
    errors    = []

    print(f"[清单] 共发现 {total} 个配置项，即将开始下载...\n")

    for idx, section in enumerate(sections, start=1):
        kv_path  = config.get(section, "Path",      fallback="").strip()
        filename = config.get(section, "File_name", fallback="").strip()

        if not kv_path or not filename:
            print(f"[跳过] [{section}] 缺少 Path 或 File_name，已跳过。")
            errors.append(section)
            continue

        print(f"[{idx}/{total}] 正在下载 [{section}]")
        try:
            local_path = download_file(path=kv_path, filename=filename)
            saved.append(local_path)
        except requests.HTTPError as e:
            print(f"  ✗ HTTP 错误：{e.response.status_code}")
            errors.append(section)
        except requests.RequestException as e:
            print(f"  ✗ 网络错误：{e}")
            errors.append(section)

        # ── 间隔等待（最后一个不等待）──
        if idx < total:
            print(f"  等待 {BATCH_INTERVAL} 秒...")
            time.sleep(BATCH_INTERVAL)

    # ── 3. 汇总 ──
    print(f"\n{'='*40}")
    print(f"下载完成：成功 {len(saved)} 个，失败 {len(errors)} 个。")
    if errors:
        print(f"失败项：{', '.join(errors)}")
    print(f"{'='*40}")

    return saved


# ============================================================
#  直接运行入口
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Cloudflare Worker 配置下载器")
    sub    = parser.add_subparsers(dest="command")

    # 子命令：单文件
    p_single = sub.add_parser("single", help="下载单个配置文件")
    p_single.add_argument("kv_path", help="KV 路径，例如 test/test1/000.yaml")

    # 子命令：批量
    p_batch = sub.add_parser("batch", help="批量下载（从远程 INI 清单）")
    p_batch.add_argument(
        "--manifest", default=None,
        help=f"INI 清单的 KV 路径（默认：{MANIFEST_PATH}）"
    )

    args = parser.parse_args()

    if args.command == "single":
        download_file(args.kv_path)
    elif args.command == "batch":
        download_batch(args.manifest)
    else:
        parser.print_help()

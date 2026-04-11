"""
config_downloader.py
--------------------
远程配置文件同步工具。
支持单文件下载、批量下载（通过远程清单文件）。
可在代码中直接定义参数，也可由其他脚本调用并传入参数。
"""

import os
import time
import configparser
import requests


# ============================================================
#  基础配置（按需修改）
# ============================================================

DOMAIN          = os.environ["DOMAIN"]           # 服务域名（无前缀，来自外部环境变量）
BASE_URL        = f"https://{DOMAIN}"            # 自动补全前缀
ACCESS_KEY      = os.environ["ACCESS_KEY"]       # 访问密钥（来自外部环境变量）
DOWNLOAD_DIR    = "./code"                  # 本地同步根目录
MANIFEST_PATH   = "iptv/code/ini/script_urls.ini"      # 远程清单文件路径
BATCH_INTERVAL  = 2.5                            # 批量同步间隔（秒）

# 路径隐藏模式：设为 True 时，终端输出不显示任何路径信息
HIDE_PATH       = False


# ============================================================
#  内部工具函数
# ============================================================

def _build_url(remote_path: str) -> str:
    """拼接完整请求地址（不对外暴露）。"""
    return f"{BASE_URL}/config/read_config/{remote_path}?token={ACCESS_KEY}"


def _post(remote_path: str) -> requests.Response:
    """发起同步请求（不打印地址）。"""
    url = _build_url(remote_path)
    response = requests.post(url, timeout=15)
    response.raise_for_status()
    return response


def _save(content: str, rel_path: str, filename: str) -> str:
    """将内容保存到本地，目录结构与远程路径保持一致。"""
    save_dir = os.path.join(DOWNLOAD_DIR, rel_path.replace("/", os.sep))
    os.makedirs(save_dir, exist_ok=True)
    filepath = os.path.join(save_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return filepath


def _mask(text: str) -> str:
    """在隐藏模式下将路径替换为占位符。"""
    return "***" if HIDE_PATH else text


# ============================================================
#  对外接口
# ============================================================

def download_file(remote_path: str = None, *, path: str = None,
                  filename: str = None, hide_path: bool = None) -> str:
    """
    下载单个配置文件。

    用法 A：直接传入完整远程路径
        download_file("test/test1/000.yaml")

    用法 B：分别传入目录和文件名
        download_file(path="test/test1", filename="000.yaml")

    hide_path：是否隐藏路径输出，不传则使用全局 HIDE_PATH 设置。

    返回：本地保存路径
    """
    _hide = HIDE_PATH if hide_path is None else hide_path

    if remote_path is None:
        if path is None or filename is None:
            raise ValueError("请提供 remote_path，或同时提供 path 和 filename。")
        remote_path = f"{path}/{filename}"
    else:
        parts    = remote_path.rsplit("/", 1)
        path     = parts[0] if len(parts) == 2 else ""
        filename = parts[-1]

    if _hide:
        print(f"[同步] {_mask(filename)}")
    else:
        print(f"[同步] {filename}  ←  {path}/")

    response = _post(remote_path)
    saved_to = _save(response.text, path, filename)

    if _hide:
        print(f"[完成] 已保存至 {_mask(saved_to)}")
    else:
        print(f"[完成] 已保存至 {saved_to}")

    return saved_to


def download_batch(manifest_path: str = None, hide_path: bool = None) -> list[str]:
    """
    批量下载：先获取远程清单文件，再逐项同步。

    manifest_path：远程清单文件路径，默认使用代码顶部定义的 MANIFEST_PATH。
    hide_path：是否隐藏路径输出，不传则使用全局 HIDE_PATH 设置。

    返回：所有成功下载的本地路径列表
    """
    _hide       = HIDE_PATH if hide_path is None else hide_path
    target_path = manifest_path or MANIFEST_PATH

    # ── 1. 拉取清单 ──
    print("[清单] 正在获取同步清单...")
    response = _post(target_path)
    raw_ini  = response.text

    # ── 2. 解析清单 ──
    config = configparser.ConfigParser()
    config.read_string(raw_ini)

    sections = config.sections()
    if not sections:
        print("[清单] 清单为空，无文件可同步。")
        return []

    total  = len(sections)
    saved  = []
    errors = []

    print(f"[清单] 共发现 {total} 个配置项，即将开始同步...\n")

    for idx, section in enumerate(sections, start=1):
        item_path = config.get(section, "Path",      fallback="").strip()
        filename  = config.get(section, "File_name", fallback="").strip()

        if not item_path or not filename:
            label = _mask(section) if _hide else section
            print(f"[跳过] [{label}] 缺少必要字段，已跳过。")
            errors.append(section)
            continue

        label = _mask(section) if _hide else section
        print(f"[{idx}/{total}] 正在同步 [{label}]")

        try:
            local_path = download_file(path=item_path, filename=filename, hide_path=_hide)
            saved.append(local_path)
        except requests.HTTPError as e:
            print(f"  ✗ 请求失败：状态码 {e.response.status_code}")
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
    print(f"同步完成：成功 {len(saved)} 个，失败 {len(errors)} 个。")
    if errors:
        err_labels = [_mask(e) if _hide else e for e in errors]
        print(f"失败项：{', '.join(err_labels)}")
    print(f"{'='*40}")

    return saved


# ============================================================
#  直接运行入口
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="远程配置文件同步工具")
    parser.add_argument(
        "--hide-path", action="store_true",
        help="隐藏终端输出中的路径信息"
    )
    sub = parser.add_subparsers(dest="command")

    # 子命令：单文件
    p_single = sub.add_parser("single", help="同步单个配置文件")
    p_single.add_argument("remote_path", help="远程路径，例如 test/test1/000.yaml")

    # 子命令：批量
    p_batch = sub.add_parser("batch", help="批量同步（从远程清单文件）")
    p_batch.add_argument(
        "--manifest", default=None,
        help=f"清单文件的远程路径（默认：{MANIFEST_PATH}）"
    )

    args = parser.parse_args()

    # 命令行参数优先于全局设置
    hide = args.hide_path if args.hide_path else HIDE_PATH

    if args.command == "single":
        download_file(args.remote_path, hide_path=hide)
    elif args.command == "batch":
        download_batch(args.manifest, hide_path=hide)
    else:
        parser.print_help()

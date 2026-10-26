import os

def export_project(
        root_dir="./",
        output="all_code.txt",
        ignore_dirs=None,
        target_exts=None,
        special_files=None,
        max_file_size: int = 1024 * 1024  # 单文件最大 1MB，超过不读取内容
):
    # 默认忽略目录
    if ignore_dirs is None:
        ignore_dirs = [
            "__pycache__", ".venv", "venv", ".git", "dist", "build",
            "node_modules", ".next", "out", ".idea", ".vscode"
        ]
    # 默认后缀
    if target_exts is None:
        target_exts = (
            ".py", ".js", ".ts", ".jsx", ".tsx", ".vue", ".html",
            ".css", ".scss", ".json", ".yaml", ".yml", ".md", ".txt", ".sql"
        )
    # 无后缀需要导出的特殊文件
    if special_files is None:
        special_files = ["Dockerfile", ".gitignore", ".env.example"]

    # realpath 归一化：跨盘符/盘符大小写/正反斜杠差异统一成规范形式
    root_dir = os.path.realpath(root_dir)
    output_path = os.path.realpath(output)
    collected_files = []
    tree_lines = []

    print(f"开始扫描目录: {root_dir} ...")

    for path, dirs, files in os.walk(root_dir):
        # 原地过滤目录，并且排个序，让导出结果更整齐
        dirs[:] = sorted([d for d in dirs if d not in ignore_dirs])
        files.sort()  # 让文件也按字母顺序排列

        rel_path = os.path.relpath(path, root_dir)
        level = rel_path.count(os.sep) if rel_path != "." else 0
        indent = " " * 4 * level

        # 记录文件夹
        tree_lines.append(f"{indent}{os.path.basename(path)}/")

        for file in files:
            filepath = os.path.join(path, file)
            # 排除导出文件自身：字符串比较在盘符大小写/分隔符差异下会失配，
            # 导致 all_code.txt 把自己包进去、重跑时越滚越大；
            # samefile 是 inode 级判断（输出文件尚不存在时回退字符串比较）
            try:
                if os.path.samefile(filepath, output_path):
                    continue
            except OSError:
                if filepath == output_path:
                    continue

            if file.endswith(target_exts) or file in special_files:
                tree_lines.append(f"{indent}    {file}")
                collected_files.append(filepath)

    # 写入文件
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("================ 项目文件树 ================\n")
        f.write("\n".join(tree_lines))

        f.write("\n\n================ 源码内容 ================\n")

        for filepath in collected_files:
            f.write(f"\n{'=' * 60}\nFILE PATH: {filepath}\n{'=' * 60}\n")
            try:
                stat = os.stat(filepath)
                if stat.st_size > max_file_size:
                    f.write(f"【跳过】文件过大({stat.st_size / 1024:.2f}KB)，超过限制 {max_file_size / 1024:.2f}KB\n")
                    continue

                with open(filepath, "r", encoding="utf-8") as codef:
                    f.write(codef.read())
            except UnicodeDecodeError:
                try:
                    with open(filepath, "r", encoding="gbk") as codef:
                        f.write(codef.read())
                except Exception as e:
                    f.write(f"【读取失败 {filepath}】编码读取异常: {str(e)}\n")
            except Exception as e:
                f.write(f"【读取失败 {filepath}】错误信息: {str(e)}\n")

    print(f"✅ 导出完成！一共导出 {len(collected_files)} 个文件")
    print(f"文件位置：{output_path}")

if __name__ == "__main__":
    export_project(
        root_dir="./",
        output="all_code.txt",
    )
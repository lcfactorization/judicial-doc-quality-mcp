import pathlib

fp = pathlib.Path(r"C:\Users\stere\Documents\Obsidian Vault\judicial-doc-quality-mcp\src\judicial_quality_mcp\server.py")
lines = fp.read_text(encoding="utf-8").splitlines(keepends=True)

# Line 1325 (0-indexed: 1324): change header
lines[1324] = '                    lines.append("| 项编号 | 异常项 | A编号 | 受益方 | 置信度 | 简述 |")\n'

# Line 1326 (0-indexed: 1325): change separator
lines[1325] = '                    lines.append("|:---:|:---|:---:|:---:|:---:|:---|")\n'

# Line 1329 (0-indexed: 1328): change f_code fallback
lines[1328] = '                        f_code = a.get("f_code", f"{dim_key[:2].upper()}-{a_idx:02d}")\n'

# Line 1334 (0-indexed: 1333): change output line
lines[1333] = '                        lines.append(f"| {f_code} | {name} | {a_code} | {beneficiary} | {confidence} | {desc} |")\n'

fp.write_text("".join(lines), encoding="utf-8")
print("Done")

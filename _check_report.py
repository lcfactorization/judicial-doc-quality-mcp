with open(r"[匿名化路径]\质量评估报告_[匿名化案号]_20260519.md", encoding="utf-8") as f:
    content = f.read()
lines = content.split("\n")

print("=" * 60)
print("1. 低风险维度显示检查")
print("=" * 60)
low_risk_dims = ["程序规范", "焦点漂移", "自由裁量", "审理过程", "外部干预", "执行问题", "语义漂移"]
for dim in low_risk_dims:
    found = dim in content
    print(f"  {'OK' if found else 'ERROR'}: {dim}")

print()
print("=" * 60)
print("2. 日期一致性检查")
print("=" * 60)
if "20260519" in r"[匿名化路径]\质量评估报告_[匿名化案号]_20260519.md":
    print("  OK: 文件名日期 20260519")
if "2026-05-19" in content:
    print("  OK: 报告内检测日期 2026-05-19")

print()
print("=" * 60)
print("3. 超长行检查 (>300字符)")
print("=" * 60)
long_lines = [(i+1, len(l)) for i, l in enumerate(lines) if len(l) > 300]
if long_lines:
    for ln, length in long_lines:
        print(f"  WARNING: Line {ln} ({length} chars): {lines[ln-1][:80]}...")
else:
    print("  OK: 无超长行")

print()
print("=" * 60)
print("4. Typora Quoteblock格式检查")
print("=" * 60)
issues = []
for i, line in enumerate(lines):
    stripped = line.rstrip("\n")
    if stripped.startswith("> [!") and "]" in stripped:
        after_bracket = stripped[stripped.index("]")+1:]
        if after_bracket.strip():
            issues.append(f"Line {i+1}: Alert type line has content after ]")
    if i > 0 and lines[i-1].rstrip("\n").startswith("> [!"):
        if not stripped.startswith("> "):
            issues.append(f"Line {i+1}: Content after alert missing '> ' prefix")
if issues:
    for iss in issues:
        print(f"  ERROR: {iss}")
else:
    print("  OK: All Quoteblock formats Typora-compatible")

print()
print("=" * 60)
print("5. 时间线异常类型检查")
print("=" * 60)
tl_types = ["程序时序", "证据时序", "法律溯及力", "内部时间矛盾"]
for t in tl_types:
    found = t in content
    print(f"  {'OK' if found else '--'}: {t}")

# Check narrative inversion is NOT in anomaly table
if "时间倒置" in content:
    # Check if it's in the anomaly table or just a note
    for i, line in enumerate(lines):
        if "时间倒置" in line and "| TL-" in line:
            print(f"  WARNING: 叙事倒置仍出现在异常表格中 (Line {i+1})")
            break
    else:
        print("  OK: 叙事结构倒置仅作为备注，不在异常表格中")
else:
    print("  OK: 无时间倒置异常条目")

# Check narrative inversion note
if "叙事结构倒置" in content:
    print("  OK: 叙事结构倒置备注存在")
else:
    print("  NOTE: 无叙事结构倒置备注")

print()
print("=" * 60)
print("6. 报告完整性检查")
print("=" * 60)
sections = ["综合评级", "各维度评分", "评分明细一览", "异常扣分明细", "创新性加分明细",
            "辅助检测结果", "时间线提取与异常检测", "规避模式检测", "证据引用追踪",
            "异常检测MCP联动结果", "检测概览", "各维度异常详情", "免责声明"]
for sec in sections:
    found = sec in content
    print(f"  {'OK' if found else 'ERROR'}: {sec}")

print()
print(f"报告总字符数: {len(content)}")
print(f"报告总行数: {len(lines)}")

# Show timeline section
print()
print("=" * 60)
print("7. 时间线检测部分内容")
print("=" * 60)
in_tl = False
for i, line in enumerate(lines):
    if "时间线提取与异常检测" in line:
        in_tl = True
    if in_tl:
        print(f"  {line}")
        if i > 0 and lines[i-1].startswith("###") and line.startswith("###") and "时间线" not in line:
            break
    if in_tl and i > 0 and "规避模式检测" in line:
        break

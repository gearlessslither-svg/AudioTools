# -*- coding: utf-8 -*-
from pathlib import Path

skill = Path(r"C:\Users\user1\.codex\skills\wwise-project-resource-audit\SKILL.md")
script = Path(r"C:\Users\user1\.codex\skills\wwise-project-resource-audit\scripts\wwise_resource_audit.py")
ref = Path(r"C:\Users\user1\.codex\skills\wwise-project-resource-audit\references\wwise-audit-standards.md")

skill_text = skill.read_text(encoding="utf-8")
if "## Upgrade Audit" not in skill_text:
    skill_text = skill_text.rstrip() + """

## Upgrade Audit

When Wwise is upgraded, the audit must additionally compare:

- Wwise Authoring version from WAAPI, if available.
- Project XML `WwiseVersion`, `WwiseBuild`, and `SchemaVersion`.
- `ProjectInfo.xml`, `PluginInfo.xml`, and `SoundbanksInfo.xml` SoundBank/schema versions.
- Migration logs such as `*_migration.log`.
- Whether generated banks are older than authored WorkUnits.
- Whether generated metadata still points to an old project root.
- Whether Unity/bank output paths still point to the intended current project.

If Authoring version and project XML version differ, do not assume the project was migrated; report it as a required manual confirmation.
"""
    skill.write_text(skill_text, encoding="utf-8")

ref_text = ref.read_text(encoding="utf-8")
if "Upgrade-specific checks" not in ref_text:
    ref_text = ref_text.rstrip() + """

## Upgrade-specific checks

- After a Wwise Authoring upgrade, verify the opened project's `.wproj` header version and schema version. A newer Authoring app does not guarantee the project files have been migrated/saved.
- Regenerate SoundBanks after structural, Event, Bus, or version migration changes before treating `SoundbanksInfo.xml` as runtime truth.
- Compare generated metadata paths against the current project root; stale roots are a strong sign of copied or old generated banks.
"""
    ref.write_text(ref_text, encoding="utf-8")

text = script.read_text(encoding="utf-8")

if "def project_version_info" not in text:
    marker = "def parse_project(root: Path, include_backups: bool = False) -> dict[str, Any]:\n"
    insert = r'''
def project_version_info(root: Path) -> dict[str, Any]:
    info: dict[str, Any] = {
        "wproj_files": [],
        "migration_logs": [],
        "project_info_xml": {},
        "plugin_info_xml": {},
    }
    for wproj in sorted(root.glob("*.wproj")):
        try:
            doc = ET.parse(wproj).getroot()
            info["wproj_files"].append(
                {
                    "file": str(wproj.relative_to(root)),
                    "type": doc.attrib.get("Type", ""),
                    "schema_version": doc.attrib.get("SchemaVersion", ""),
                    "wwise_version": doc.attrib.get("WwiseVersion", ""),
                    "wwise_build": doc.attrib.get("WwiseBuild", ""),
                    "mtime": dt.datetime.fromtimestamp(wproj.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
        except Exception as exc:
            info["wproj_files"].append({"file": str(wproj.relative_to(root)), "error": str(exc)})

    for log in sorted(root.glob("*migration*.log")):
        try:
            content = log.read_text(encoding="utf-8", errors="replace")
            lines = [line.strip() for line in content.splitlines() if line.strip()]
            info["migration_logs"].append(
                {
                    "file": str(log.relative_to(root)),
                    "size_kb": round(log.stat().st_size / 1024, 1),
                    "mtime": dt.datetime.fromtimestamp(log.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    "tail": lines[-12:],
                }
            )
        except Exception as exc:
            info["migration_logs"].append({"file": str(log.relative_to(root)), "error": str(exc)})

    for rel, key in [
        (Path("GeneratedSoundBanks") / "ProjectInfo.xml", "project_info_xml"),
        (Path("GeneratedSoundBanks") / "Windows" / "PluginInfo.xml", "plugin_info_xml"),
    ]:
        path = root / rel
        if not path.exists():
            continue
        try:
            doc = ET.parse(path).getroot()
            info[key] = {
                "file": str(rel),
                "root_tag": strip_ns(doc.tag),
                "attributes": dict(doc.attrib),
                "mtime": dt.datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            }
        except Exception as exc:
            info[key] = {"file": str(rel), "error": str(exc)}
    return info

'''
    text = text.replace(marker, insert + "\n" + marker)

if "version_info = project_version_info(root)" not in text:
    text = text.replace(
        "parsed = parse_project(root, args.include_backups)\n",
        "version_info = project_version_info(root)\n    parsed = parse_project(root, args.include_backups)\n",
    )
    text = text.replace(
        "report = generate_report(root, parsed, file_scan, banks, extras, live, analysis)\n",
        "report = generate_report(root, version_info, parsed, file_scan, banks, extras, live, analysis)\n",
    )
    text = text.replace(
        '"project_root": str(root),\n',
        '"project_root": str(root),\n            "version_info": version_info,\n',
    )

text = text.replace(
    "def build_issue_table(root: Path, file_scan: dict[str, Any], banks: dict[str, Any], extras: dict[str, Any], analysis: dict[str, Any]) -> list[list[str]]:",
    "def build_issue_table(root: Path, version_info: dict[str, Any], file_scan: dict[str, Any], banks: dict[str, Any], extras: dict[str, Any], analysis: dict[str, Any]) -> list[list[str]]:",
)

if "Project XML WwiseVersion 与本次升级目标不一致" not in text:
    anchor = "rows: list[list[str]] = []\n"
    upgrade_issue = r'''    for item in version_info.get("wproj_files", []):
        xml_version = item.get("wwise_version", "")
        if xml_version and xml_version != "v2024.1.13":
            rows.append(
                [
                    "Project XML WwiseVersion 与本次升级目标不一致",
                    f"`.wproj` 仍记录 `{xml_version}` / build `{item.get('wwise_build', '')}` / schema `{item.get('schema_version', '')}`；可能是只升级了 Authoring，但工程还没用 2024.1.13 打开保存，或当前检测路径不是刚升级的工程。",
                    "团队会误以为工程已迁移；SoundBank、插件、Unity integration 排查时版本基准会混乱。",
                    "用 Wwise 2024.1.13 打开当前 `.wproj`，确认迁移提示并保存；然后重新生成 SoundBanks 并重新跑检测。",
                ]
            )
    if not version_info.get("migration_logs"):
        rows.append(
            [
                "未发现新的 migration log",
                "可能工程未触发迁移、迁移日志写到别处，或 Wwise 版本升级不需要 schema 迁移。",
                "如果同时 `.wproj` 版本仍旧，就无法确认工程已完成 2024.1.13 迁移。",
                "保存工程后检查根目录 migration log；必要时保留升级前备份并记录迁移结论。",
            ]
        )
'''
    text = text.replace(anchor, anchor + upgrade_issue, 1)

text = text.replace(
    "def generate_report(root: Path, parsed: dict[str, Any], file_scan: dict[str, Any], banks: dict[str, Any], extras: dict[str, Any], live: dict[str, Any], analysis: dict[str, Any]) -> str:",
    "def generate_report(root: Path, version_info: dict[str, Any], parsed: dict[str, Any], file_scan: dict[str, Any], banks: dict[str, Any], extras: dict[str, Any], live: dict[str, Any], analysis: dict[str, Any]) -> str:",
)
text = text.replace(
    "issue_rows = build_issue_table(root, file_scan, banks, extras, analysis)",
    "issue_rows = build_issue_table(root, version_info, file_scan, banks, extras, analysis)",
)

if "## 2.0 升级版本检查" not in text:
    marker = '"## 2. 总体结论",\n'
    # Insert after summary table block by adding section right before 2.1.
    target = '"## 2.1 不合理点：可能原因与修改意见",\n'
    replacement = '''"## 2.0 升级版本检查",
        "",
        table([[x.get("file", ""), x.get("wwise_version", ""), x.get("wwise_build", ""), x.get("schema_version", ""), x.get("mtime", "")] for x in version_info.get("wproj_files", [])], ["wproj", "WwiseVersion", "Build", "SchemaVersion", "修改时间"]) if version_info.get("wproj_files") else "未找到 .wproj。",
        "",
        "Migration logs：",
        "",
        table([[x.get("file", ""), x.get("size_kb", ""), x.get("mtime", ""), " / ".join(x.get("tail", [])[-3:])] for x in version_info.get("migration_logs", [])], ["文件", "KB", "修改时间", "末尾摘要"]) if version_info.get("migration_logs") else "未发现 migration log。",
        "",
        "Generated ProjectInfo / PluginInfo：",
        "",
        table([["ProjectInfo.xml", version_info.get("project_info_xml", {}).get("root_tag", ""), json.dumps(version_info.get("project_info_xml", {}).get("attributes", {}), ensure_ascii=False), version_info.get("project_info_xml", {}).get("mtime", "")], ["PluginInfo.xml", version_info.get("plugin_info_xml", {}).get("root_tag", ""), json.dumps(version_info.get("plugin_info_xml", {}).get("attributes", {}), ensure_ascii=False), version_info.get("plugin_info_xml", {}).get("mtime", "")]], ["文件", "RootTag", "Attributes", "修改时间"]),
        "",
        "## 2.1 不合理点：可能原因与修改意见",
'''
    text = text.replace(target, replacement)

script.write_text(text, encoding="utf-8")
print("updated")

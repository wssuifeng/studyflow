"""StudyFlow MSI 安装包机器核验（可复用）。

WiX dark 解包 → Installer 校验（MsiVerifyPackageW）→ 属性回读 → 载荷逐项 SHA-256：
Skill 源文件按相对路径匹配，CLI/Engine 与构建资源匹配，桌面 EXE 版本与 release 原文件
字节比较（仅允许 BUNDLE_TYPE_VAR 标记差异）。签名状态经 Get-AuthenticodeSignature 回读。
回执写入 Git 忽略的 test-results/msi-<version>-verify/verification.json。

运行：py -3 -X utf8 apps/desktop/scripts/verify-msi.py --msi <path.msi> [--dark <dark.exe>]
"""
import argparse
import ctypes
import hashlib
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DESKTOP = ROOT / 'apps/desktop'


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def wxs_properties(root) -> dict:
    props = {p.get('Id'): p.get('Value') for p in root.iter('Property')}
    product = next(root.iter('Product'), None)
    if product is not None:
        props.update({'ProductName': product.get('Name'), 'ProductVersion': product.get('Version'),
                      'ProductCode': product.get('Id'), 'UpgradeCode': product.get('UpgradeCode'),
                      'Manufacturer': product.get('Manufacturer'), 'Language': product.get('Language')})
    package = next(root.iter('Package'), None)
    props['Platform'] = package.get('Platform') if package is not None else None
    return props


def parse_payload_map(root) -> dict:
    """返回 {载荷文件名(File Id): 相对 INSTALLDIR 的路径}。"""
    mapping = {}

    def walk(node, trail):
        for child in node:
            if child.tag == 'Directory':
                if child.get('Id') == 'INSTALLDIR':
                    walk(child, [])
                else:
                    walk(child, trail + [child.get('Name') or child.get('Id')])
            elif child.tag == 'File':
                rel = '/'.join(trail + [child.get('Name')])
                mapping[child.get('Id')] = rel
            else:
                walk(child, trail)

    walk(root, [])
    return mapping


def windows_powershell(command: str, path: Path) -> str:
    # PowerShell 7 can pass its module search path to Windows PowerShell 5.1.
    env = {key: value for key, value in os.environ.items() if key.upper() != 'PSMODULEPATH'}
    env['STUDYFLOW_VERIFY_FILE'] = str(path)
    result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', command],
                            env=env, capture_output=True, text=True, errors='replace')
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return result.stdout.strip()


def exe_version(path: Path) -> str:
    return windows_powershell('(Get-Item -LiteralPath $env:STUDYFLOW_VERIFY_FILE).VersionInfo.ProductVersion', path)


def signature_status(msi: Path) -> str:
    return windows_powershell('(Get-AuthenticodeSignature -LiteralPath $env:STUDYFLOW_VERIFY_FILE).Status', msi)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--msi', required=True)
    parser.add_argument('--dark', default=str(Path.home() / 'AppData/Local/tauri/WixTools314/dark.exe'))
    parser.add_argument('--desktop', type=Path, default=DESKTOP / 'src-tauri/target/release/studyflow-desktop.exe')
    parser.add_argument('--resources', type=Path, default=DESKTOP / 'src-tauri/binaries')
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args()
    msi = Path(args.msi).resolve()
    match = re.fullmatch(r'StudyFlow_(\d+\.\d+\.\d+)_x64_en-US\.msi', msi.name)
    if not match:
        raise SystemExit('Expected the StudyFlow x64 en-US MSI filename')
    version = match.group(1)
    verify_root = (args.evidence or DESKTOP / 'test-results' / f'msi-{version}-verify').resolve()
    verify_root.mkdir(parents=True, exist_ok=True)
    payload = verify_root / 'payload'
    wxs = verify_root / 'decompiled.wxs'

    # WiX dark 解包（DARK1059 UI 反编译警告为已知模板警告，不否定独立核验）。
    proc = subprocess.run([args.dark, '-x', str(payload), '-out', str(wxs), str(msi)],
                          capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=verify_root)
    if proc.returncode != 0:
        print(proc.stdout, proc.stderr)
        raise SystemExit(f'dark failed: {proc.returncode}')

    verify_code = ctypes.windll.msi.MsiVerifyPackageW(str(msi))
    root = ET.parse(wxs).getroot()
    for el in root.iter():
        el.tag = el.tag.split('}')[-1]
    props = wxs_properties(root)
    mapping = parse_payload_map(root)
    hashes = {file_id: sha256(payload / 'File' / file_id) for file_id in mapping}
    by_rel = {rel: hashes[file_id] for file_id, rel in mapping.items()}

    # Skill：源目录有效文件（排除 bytecode/缓存）逐项相对路径+哈希匹配。
    skill_source = ROOT / 'skills/studyflow-agent'
    skill_files = [p for p in skill_source.rglob('*') if p.is_file()
                   and p.suffix in ('.md', '.json', '.yaml', '.yml')
                   and '__pycache__' not in p.parts and '.pytest_cache' not in p.parts]
    mismatches = []
    matched = 0
    for p in skill_files:
        rel = 'binaries/studyflow-agent/' + p.relative_to(skill_source).as_posix()
        if by_rel.get(rel) == sha256(p):
            matched += 1
        else:
            mismatches.append(rel)

    binaries = args.resources.resolve(strict=True)
    cli_rel = 'binaries/studyflow.exe'
    engine_rel = 'binaries/studyflow-engine.exe'
    desktop_rel = 'studyflow-desktop.exe'
    expected_paths = {cli_rel, engine_rel, desktop_rel} | {
        'binaries/studyflow-agent/' + p.relative_to(skill_source).as_posix() for p in skill_files}
    unexpected_paths = sorted(set(by_rel) - expected_paths)
    missing_paths = sorted(expected_paths - set(by_rel))
    release_exe = args.desktop.resolve(strict=True)
    payload_exe = next(payload / 'File' / fid for fid, rel in mapping.items() if rel == desktop_rel)
    src_bytes, dst_bytes = release_exe.read_bytes(), payload_exe.read_bytes()
    diffs = [i for i, (a, b) in enumerate(zip(src_bytes, dst_bytes)) if a != b]
    marker = b'__TAURI_BUNDLE_TYPE_VAR_UNK'
    marker_only = (src_bytes.count(marker) == 1 and src_bytes.replace(marker, b'__TAURI_BUNDLE_TYPE_VAR_MSI') == dst_bytes)
    config = json.loads((DESKTOP / 'src-tauri/tauri.conf.json').read_bytes())
    bootstrapper = any(el.get('Id') == 'DownloadAndInvokeBootstrapper' for el in root.iter('CustomAction'))
    context = src_bytes[max(0, diffs[0] - 16):diffs[0] + 24].decode('latin-1') if diffs else ''

    result = {
        'msi': str(msi),
        'bytes': msi.stat().st_size,
        'sha256': sha256(msi),
        'signature_status': signature_status(msi),
        'msi_verify_package_w': verify_code,
        'installer': {k: props.get(k) for k in ('ProductName', 'ProductVersion', 'ProductCode', 'UpgradeCode', 'Manufacturer', 'Language', 'Platform')},
        'webview2_download_bootstrapper': bootstrapper,
        'payload_file_count': len(mapping),
        'payload_files': by_rel,
        'unexpected_paths': unexpected_paths,
        'missing_paths': missing_paths,
        'skill': {'version': (skill_source / 'SKILL.md').read_text(encoding='utf-8').split('version:')[1].split('\n')[0].strip().strip('"') if 'version:' in (skill_source / 'SKILL.md').read_text(encoding='utf-8') else 'unknown',
                  'source_files': len(skill_files), 'payload_matches': matched, 'mismatches': mismatches},
        'cli': {'source_sha256': sha256(binaries / 'studyflow.exe'), 'payload_sha256': by_rel.get(cli_rel),
                'matched': by_rel.get(cli_rel) == sha256(binaries / 'studyflow.exe')},
        'engine': {'source_sha256': sha256(binaries / 'studyflow-engine.exe'), 'payload_sha256': by_rel.get(engine_rel),
                   'matched': by_rel.get(engine_rel) == sha256(binaries / 'studyflow-engine.exe')},
        'desktop': {'source_bytes': len(src_bytes), 'payload_bytes': len(dst_bytes),
                    'source_version': exe_version(release_exe), 'payload_version': exe_version(payload_exe),
                    'differing_byte_count': len(diffs), 'differing_offsets': diffs[:8],
                    'diff_source_context': context, 'bundle_marker_only': marker_only},
        'dark_warnings': [line for line in ((proc.stdout or '') + (proc.stderr or '')).splitlines() if 'warning' in line.lower()][:4],
    }
    (verify_root / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    ok = (verify_code == 0 and not mismatches and len(mapping) == len(expected_paths)
          and not unexpected_paths and not missing_paths and result['cli']['matched'] and result['engine']['matched']
          and result['desktop']['source_version'] == result['desktop']['payload_version'] == version
          and (src_bytes == dst_bytes or marker_only) and bootstrapper
          and props['ProductName'] == config['productName'] and props['ProductVersion'] == version
          and props['Platform'] == 'x64' and props['Language'] == '1033'
          and props['UpgradeCode'].strip('{}').lower() == config['bundle']['windows']['wix']['upgradeCode'])
    print(json.dumps({'ok': ok, 'version': version, 'verify_code': verify_code,
                      'skill': f"{matched}/{len(skill_files)}", 'payload_files': len(mapping),
                      'desktop_diff_bytes': len(diffs), 'sha256': result['sha256']}, ensure_ascii=False))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
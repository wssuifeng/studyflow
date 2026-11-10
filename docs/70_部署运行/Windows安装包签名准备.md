# Windows安装包签名准备

适用：StudyFlow Windows Authenticode代码签名。2026-10-18按用户选择完成个人本地自签；当前发布者字段为`wssuifeng`。桌面/Core/CLI/Engine1.8.9，当前交付为MSI。用户已于2026-10-18确认1.8.9 MSI安装成功；不据此推导全部升级场景或用户体验通过。

2026-10-19增量：1.8.10 MSI已沿用个人签名与RFC3161，Windows仍不信任自签根；版本/42文件/升级标识核对通过。本次直接WiX链接实际运行ICE，有4条模板警告，不沿用1.8.9的ICE未运行结论。未自动安装。详见[构建记录](../40_开发实施/2026-10-19-1.8.10构建与构建产物清理记录.md)。

## 当前已完成

| 项目 | 结果 |
|---|---|
| 安装包发布者 | `bundle.publisher=wssuifeng`，桌面EXE公司字段/MSI Manufacturer已核对 |
| 签名证书 | 个人自签`CN=wssuifeng`，RSA3072，SHA256，Code Signing用途；有效期至2029-10-18 |
| 本机定位 | 证书和私钥在当前用户My库；通过指纹选择，不在公开配置写入本机证书信息 |
| 本地备份 | 仓库外私人维护目录保存加密PFX、公钥CER、DPAPI保护密码及本地Tauri签名配置；PFX实际打开验证通过 |
| 签名范围 | 桌面EXE、冻结Engine、冻结CLI、最终MSI |
| 时间戳 | DigiCert RFC3161/SHA256，四个文件均查到时间戳证书 |
| Windows信任结果 | 自签根未受信任，Get-AuthenticodeSignature=UnknownError；SignTool标准策略报告不受信任根，不能记为Valid |
| 系统变更边界 | 未向Root或TrustedPublisher导入；未自动安装、修改系统服务或系统ACL |

自签只建立本地签名身份，不赋予公共信任或消除SmartScreen信誉提示。安装包元数据发布者与代码签名主体分别核对；Windows安全提示仍可能显示未知发布者。需要公众默认信任时，应另行配置受Windows信任链认可的代码签名证书或托管签名服务。

## 可复用签名流程

1. 构建Engine/CLI，使用本地证书库指纹和SHA256签名，附RFC3161时间戳。
2. 使用私人本地JSON通过`--config`传入Windows签名配置；不将PFX、密码、私钥或机器专用配置写入公开仓库。
3. 构建桌面并封装MSI。已签名桌面再次封装时使用`bundle --no-binary-patching`，防止后续补丁破坏签名；资源若重复签名，须在最终封装前固定其最终字节。
4. 最终MSI签名后不再修改，重新计算交付SHA256，核对签名主体/时间戳/系统信任结果，并独立检查包数据库、解包哈希与升级标识。

本地配置形状如下，示例不是实际凭据：

```json
{
  "bundle": {
    "windows": {
      "digestAlgorithm": "sha256",
      "certificateThumbprint": "实际代码签名证书指纹，仅存本地配置",
      "timestampUrl": "实际可用的RFC3161时间戳服务",
      "tsp": true
    }
  }
}
```

DPAPI保护的密码通常绑定当前Windows用户/本机，迁移证书前应安全转移其解密方式。证书备份校验采用内存临时密钥，不导入额外证书库。

## 发布者变更与安装兼容

`bundle.windows.wix.upgradeCode`显式保持既有值；WiX兼容片段只在没有显式/新publisher目录时使用旧publisher的HKCU目录。最终MSI会话的AppSearch与属性赋值已只读验证成功；未执行实际安装升级。包有效性与42个内含文件哈希核对通过；当前构建环境ICE未执行，不能称完整ICE通过。

本次不生成Tauri updater密钥，不启用自动更新，不改公共Skill或真实学习数据。完整交付与证据索引见[1.8.9打包记录](../40_开发实施/2026-10-18-1.8.9重置入口打包记录.md)。参数依据为本机tauri-utils 2.10.0、CLI schema和Windows SDK SignTool帮助，结果来自实际签名/验证回执。

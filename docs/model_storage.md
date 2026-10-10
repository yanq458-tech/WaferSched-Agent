# 模型版本与存储方案

发布项目版本为 WaferSched-Agent 0.1.0；迁移的第五阶段模型集合标记为 `legacy-stage5`，不表示本次重新训练。来源、文件路径和 SHA256 见 `provenance/migration_manifest.json`、`results/wafer_sched/stage5/verification.json` 及 `results/release_validation/history.json`。

14 个原始模型 ZIP（正式训练的 12 个 best/final，加上 smoke 的 2 个）完整保留于 `results/wafer_sched/stage5/training/` 和 `smoke/`，总计约 1.09 MB。本次可以全部直接纳入 Git，无需 LFS 或外部下载。正式 GitHub 发布经用户确认完成后，克隆仓库即可取得这些模型及相邻 metadata；目前没有创建远程仓库、公开 Release 或实际下载 URL。

可复核模型完整性及历史指标：

```powershell
.\.venv\Scripts\python.exe scripts/verify_history.py --output results/local/model-check.json
```

GitHub 对常规 Git 中超过 50 MiB 的文件发出警告，超过 100 MiB 则阻止推送；浏览器上传的单文件限制为 25 MiB。当前最大待上传文件约 3.19 MB。依据：[GitHub 大文件说明](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)。

如果后续训练产生大模型，应保留同一模型版本的 ZIP、metadata、SHA256SUMS 和训练配置，通过 Git LFS 或版本化 GitHub Release assets 分发。README 必须列出真实 owner/repo/tag、下载命令和校验值；不能删除权重后只保留一句“另行下载”。以下仅为未来发布后的命令模板，当前不可当作真实下载地址：

```text
gh release download <真实发布tag> --repo <真实owner/repo> --pattern 'models-*.zip'
```

下载后先比对 SHA256，再加载模型。旧版本的模型和实验记录应继续保留，避免覆盖历史版本。

# scripts/ 索引

面向使用者的入口脚本。全部只用 Python 标准库，动词开头命名，Windows 上直接用 `python scripts/<名字>.py`。

| 文件 | 用途 | 生成方式 |
|---|---|---|
| `launcher.py` | **统一启动器**（v0.1.2 阶段三）：启动 / 状态 / 停止 / 重启 / 日志 / 自检 + 交互菜单；后台运行写 `data/awfm.pid`，停止只认该 PID 且必须是 python 进程，未确认绝不强制终止。`run.bat` / `run.sh` 只是它的外壳 | 手写（v0.1.2 阶段三） |
| `start.py` | 前台启动的**兼容入口**（薄包装：检查 Python ≥ 3.10、钉 UTF-8、切到项目根目录后调用 `app.main.main`），透传 `--init-config` / `--check` / `--port` 等参数；等价 `run.bat start --foreground` | 手写（阶段 06） |
| `test.py` | 四层测试批量运行器（unit / integration / security / e2e）+ 语法校验，输出用例数与跳过数汇总表 | 手写（阶段 06） |
| `build.py` | 八项静态校验：Python 版本、语法校验、零第三方依赖、前端离线、凭据纪律、错误模型回归、版本一致性、测试包结构；`--json` 出机器可读结果 | 手写（阶段 06） |
| `package.py` | 打包便携版：先跑 build.py 的校验，再暂存目录树 → 打 zip → 生成 `MANIFEST.json` 与 `SHA256SUMS.txt` 并自检 | 手写（阶段 06） |
| `testbed_wsl.sh` | WSL 测试床（决策 D-012）：以普通用户跑非 root sshd 供集成测试使用，幂等，`up` / `status` / `stop` | 手写（阶段 06，布局实测自 2026-10-15） |

## 运行示例

```powershell
.\run.bat                                    # 统一入口（交互菜单：启动/状态/停止/日志/自检）
.\run.bat check                              # 启动前自检
.\run.bat start                              # 后台启动（Linux/macOS：./run.sh start）
python scripts/start.py --check              # 前台兼容入口的自检写法
python scripts/test.py                       # 四层测试 + 语法校验
python scripts/test.py --fast                # 只跑 unit + security
python scripts/build.py                      # 静态校验
python scripts/package.py                    # 打便携版到 dist/
wsl -d Ubuntu bash scripts/testbed_wsl.sh up  # 起 WSL 测试床
```

退出码约定：`launcher.py` 0 成功 / 1 失败 / 2 用法错误 / **3 状态与请求不一致**（已经在跑、或没在跑——如实报告，不算失败）；`start.py` 与 `app/main.py` 一致（0 正常 / 1 自检未通过 / 2 启动前失败）；`test.py` 0 全过 / 1 有层未过 / 2 用法或语法校验失败；`build.py` 0 全过 / 1 有检查失败；`package.py` 0 成功 / 1 校验或自检失败 / 2 缺前置文件。

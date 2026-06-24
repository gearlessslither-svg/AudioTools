# 截图转 Excel 留档工具

## 启动

双击仓库根目录的 `Start_Screenshot_To_Excel.cmd`。

## 会捕获什么

- `PrintScreen` 或 `Win+Shift+S` 后进入剪贴板的截图。
- `Win+PrintScreen` 写入的系统截图目录。
- Xbox Game Bar 常用的 `Videos\Captures` 目录。
- OneDrive 下常见的 `Pictures\Screenshots` / `屏幕截图` 目录。

## 输出规则

输出目录：

`G:\AI\Material\Wwise\Reports\ScreenshotCapture`

第一张截图出现后，工具会先生成一个临时 Excel：

`截图留档_YYYYMMDD_HHMMSS_running.xlsx`

关闭工具后，如果本次有截图，会生成最终 Excel：

`截图留档_开始时间-结束时间.xlsx`

同时会生成同名 `_images` 文件夹保存原始图片和缩略图。Excel 内包含序号、捕获时间、来源、尺寸、原图路径、备注、缩略图。

如果本次没有截图，不会创建 Excel。

## 建议用法

跑测时只需要让窗口开着。看到一闪而过的内容就按系统截图键；测试结束后点击“停止并生成 Excel”或关闭窗口，再在最终 Excel 里统一写备注。

不建议在工具运行中编辑 `running.xlsx`，因为它会被持续刷新。备注建议写在最终 Excel 里。

# AnnoDesk 用户指南

AnnoDesk 用于标注图像中的检测框和实例分割 mask，可导入已有 YOLO 检测标签，再根据框生成分割结果并人工复核。界面为英文、浅色主题，在浏览器中使用；图片、模型和标注数据保存在运行后端的电脑上。

本指南面向安装 wheel 的使用者，不需要源码仓库、Node.js 或前端构建工具。

## 1. 安装

需要 Python 3.11 或更新版本。建议使用独立 Python 环境：

```sh
python -m venv .venv
```

macOS / Linux 激活环境：

```sh
source .venv/bin/activate
```

Windows PowerShell 激活环境：

```powershell
.\.venv\Scripts\Activate.ps1
```

安装拿到的 wheel；文件名中的版本号以实际发布文件为准：

```sh
python -m pip install ./annodesk-0.1.0-py3-none-any.whl
```

基础安装即可使用框标注、类别、审核状态和数据管理。若需要 SAM 推理，显式安装可选依赖：

```sh
python -m pip install "./annodesk-0.1.0-py3-none-any.whl[inference]"
annodesk doctor
```

`doctor` 只检查 torch / ultralytics 是否安装，不验证权重、显卡驱动或推理结果。PyTorch 的 GPU 环境需根据实际机器自行准备；SAM 3 文本推理还需要对应的本地 tokenizer / runtime 依赖。

安装依赖可能访问 Python 包索引；模型推理不会自动下载权重，也不会自动安装缺失依赖。

## 2. 启动和打开数据集

```sh
annodesk serve --project /data/my-dataset --open
```

默认地址为 `http://127.0.0.1:8765`。`--open` 请求打开浏览器；也可手动访问该地址。终端保持运行，按 Ctrl+C 停止服务。

也可先启动，再在页面点击 **Open project…** 输入路径：

```sh
annodesk serve
```

未打开项目时显示空白工作台属于正常状态。路径始终指向后端电脑，不是浏览器电脑。端口被占用时可换端口：

```sh
annodesk serve --port 8766
```

同一数据集目前请只运行一个后端进程，避免多处同时修改。

## 3. 准备数据集

推荐工作目录结构：

```text
my-dataset/
├── images/
│   ├── train/camera_a/001.jpg
│   └── val/camera_b/002.jpg
├── labels/                 # YOLO detection 标签；可选
├── labels_seg/             # YOLO segmentation 标签；可选
└── data.yaml               # 类别名称；可选
```

`train` / `val` / `test` 不是打开项目的必要条件，允许多级子目录。标签路径与图片在 `images/` 下的相对路径对应，例如：

```text
images/train/camera_a/001.jpg
labels/train/camera_a/001.txt
labels_seg/train/camera_a/001.txt
```

图片可以尚无标签；没有 `data.yaml` 时，AnnoDesk 会创建它。已有标签但缺少类别名时初始化为 `class_0` 等占位名称。也允许直接打开图片目录；此时标签和 `.annodesk/` 会写到这个目录下，建议使用独立工作目录。

同一目录下的 `001.jpg` 与 `001.png` 会争用同一个标签文件，需先重命名。导入已有 detection 和 segmentation 标签时，目前会分别创建实例，不自动匹配合并。

### 工作文件与备份

- `labels/`：显式画出的检测框；mask-only 标注不会凭空生成框。
- `labels_seg/`：分割结果的 YOLO polygon 投影。
- `.annodesk/`：实例、无损 mask RLE、审核状态、提示、任务进度和恢复信息。
- `data.yaml`：类别名称等数据集配置。

备份时保留整个工作目录，尤其不要遗漏 `.annodesk/`。YOLO polygon 不能完整表达孔洞，不能替代内部无损 mask 数据。项目已打开时不要同时用其他工具修改标签；检测到外部修改后，保存会报冲突，需要先备份并核对文件。

## 4. 配置本地 SAM 模型

创建自己的 `models.json`，例如：

```json
{
  "default_model": "sam2-small",
  "models": [
    {
      "id": "sam2-small",
      "name": "SAM 2.1 Small",
      "backend": "sam2",
      "source": "facebook/sam2.1-hiera-small"
    },
    {
      "id": "mobile",
      "name": "MobileSAM",
      "backend": "mobile_sam",
      "source": "/srv/models/MobileSAM"
    }
  ]
}
```

- `id`：唯一标识，供 `--model` 和默认模型引用。
- `name`：页面显示名称。
- `backend`：`sam`、`sam2`、`mobile_sam` 或 `sam3`。
- `source`：模型的最终一级文件夹，不填写 `.pt` / `.safetensors` 文件，也不填写 `checkpoint` 字段。

### 目录查找规则

展开 `~` 和环境变量后：

1. 绝对路径直接检查该目录，缺失则报错，不添加前缀。
2. 相对路径先相对 JSON 所在目录解析，存在目录则使用。
3. 相对目录不存在时，再检查 `$HF_MODELS/<source>`；`HF_MODELS` 未设置则不回退。

repo ID 与相对目录采用相同规则，不访问 Hugging Face。例如 JSON 位于 `/work/models.json`，`source` 为 `facebook/sam2.1-hiera-small`，先检查 `/work/facebook/sam2.1-hiera-small`，再检查 `$HF_MODELS/facebook/sam2.1-hiera-small`。

macOS / Linux 可设置：

```sh
export HF_MODELS=/srv/models
```

Windows PowerShell 可设置：

```powershell
$env:HF_MODELS = "D:\models"
```

适配器在所选目录的顶层查找权重，优先匹配该 backend 的已知 `.pt` 文件名；没有已知命名时，只接受唯一的 `.pt` 文件。存在多个候选会报错，请每个目录只放一个模型。

**当前适配器使用 Ultralytics 兼容的 `.pt` 权重。** 目录来自 Hugging Face 并不代表格式一定兼容；仅含 safetensors 的目录暂不支持。既有目录中缺少兼容权重时不会偷偷换目录或下载。真实模型和加速设备兼容性需在目标机器验证。

### 使用配置与切换模型

```sh
annodesk models list --models-config ./models.json
annodesk serve --project /data/my-dataset --models-config ./models.json
```

配置查找优先级：`--models-config` > `ANNODESK_MODELS_CONFIG` 环境变量 > 当前目录 `models.json` > 源码仓库默认（若存在）> 安装包内置默认。

建议始终显式传入自己的配置文件。页面顶部选择模型，修改 JSON 或放好模型后点击 **Reload**；`(missing)` 表示目录或兼容权重未就绪，指向提示可查看原因。模型目录存在不代表推理依赖已经全部安装。

## 5. 在页面中标注

### 浏览图片和设置类别

左上图片列表支持 **Tree / Flat**、搜索和展开目录；底部缩略图可左右滚动，图片按需加载。拖动面板之间的分隔条可调整比例。

左下 **Class palette** 是赋类入口：

- 没有选中实例时，点击类别设置新标注的默认类别。
- 点击 **Default class** 取消实例选择，回到默认类别设置。
- 选中框或 mask 后，点击类别直接修改该实例。
- 按 **C** 打开类别搜索，↑↓ 选择、Enter 确认、Esc 取消；选择模式下双击实例也可打开。

顶部 **Manage classes** 用于增加类别、修改名称和颜色。类别 ID 平时保持稳定；**Reindex IDs…** 会修改整个项目的类别映射和标签文件，使用前备份项目。

### 画框和生成 mask

1. 在 Class palette 中选择类别。
2. 使用 **Draw box** 拖出检测框，切回 **Select** 后可移动和拖动控制点调整；右侧也可编辑坐标。
3. 选中框后按 Enter，或点击 **Refine mask**，使用当前模型生成 mask。
4. **Segment current** 处理当前图片中尚无 mask 的未锁定检测框。

仅需要 mask、不希望保存检测框时，使用 **Box prompt: mask only**，或用正负点建立提示，再执行分割。框提示与显式检测框分开保存。正点用于包含区域，负点用于排除区域。文本提示工具只适用于支持文本提示的 SAM 3 模型，需先设置默认类别。

开启 **Auto-segment** 后，切换到含待处理检测框的图片会自动发起分割。**Batch…** 可对整个项目的已有框进行批量处理，在任务抽屉查看进度、错误和取消/继续操作。取消在当前图片完成后生效，继续只处理未处理图片；失败图片可在问题解决后重新发起批次。

选中实例可在右侧删除、锁定或隐藏。锁定后先解锁才能改类；隐藏只影响显示，不等于从导出中移除。画布支持滚轮局部缩放、平移和 **Fit image**。

### 保存、复核与标签

编辑会自动保存，切换图片前也会保存。底部显示保存状态；失败时查看错误并使用 **Retry save**，确认保存成功后再关闭页面。

右侧审核状态为：

| 状态 | 含义 |
| --- | --- |
| Not reviewed | 尚未人工复核 |
| Approved | 当前任务已复核通过 |
| Needs review | 当前任务需要再次检查 |
| Excluded | 整张图片不参与处理和导出；不直接删除图片 |

Detection 与 segmentation 的前三个审核状态分别记录；Excluded 作用于整张图片，可再次点击取消。编辑标注后可能恢复为未审核，需要重新确认。

图片可添加自定义 tags（逗号分隔）和 notes。顶部 **Tags** 抽屉展示只读的四个内置审核状态，下方管理自定义 tag 名称和颜色。当前自定义 tag 改名不会批量迁移旧图片上的 tag 字符串，需自行核对。

### 导出

先选中 detection 或 segmentation 任务并完成复核，再点击 **Export**。当前页面导出当前任务的 YOLO 数据集，不是只导出当前图片。

默认跳过未审核、Needs review、Excluded 和含未分配类别实例的图片；无对象图片需明确勾选 **Confirm no objects for this task** 并复核通过，才能作为空标签样本导出。

结果位于后端项目的 `.annodesk/exports/<id>/`，页面返回路径。导出目录包含复制的图片、标准 `labels/`、类别配置及报告；分割工作目录中的 `labels_seg/` 在导出副本中转换为标准 `labels/`。导出类别 ID 可能连续重排，工作项目不受影响。

YOLO polygon 对孔洞等结构可能有损，请保留原始项目及内部 RLE。当前界面还没有 COCO 导出选项和回收站管理界面。

## 6. 不打开页面，直接将检测框批量分割

```sh
annodesk segment --project /data/my-dataset --models-config ./models.json --model sam2-small
```

省略 `--model` 使用 JSON 中的 `default_model`。该命令不启动 HTTP 服务或浏览器。

- 保留 detection 框及类别，分割写入 `labels_seg/`，内部保存无损 RLE。
- 跳过已有 mask、锁定实例和 Excluded 图片。
- 每张图片独立保存；中断后再次运行可跳过已完成结果。
- 控制台输出处理进度，错误报告位于 `.annodesk/segment-report.json`。
- 成功退出码为 0；有失败图片时为 1。解决原因后可重新运行。

生成结果仍需在页面人工复核，命令不会自动标为 Approved。

## 7. 快捷键

输入框、类别搜索和 IME 输入期间不会触发工作台单键快捷键。页面 **Shortcuts ?** 可搜索快捷键；按钮提示约 150ms 后显示。

| 操作 | 按键 |
| --- | --- |
| 上一张 / 下一张 | A / D or ← / → |
| 选择 / 画框 | V / R |
| 正点 / 负点 | Q / E |
| mask 框提示 / 文本提示 | B / T |
| 执行当前实例分割 | Enter |
| 修改选中实例类别 | C or double-click |
| 删除选中实例 | X or Delete |
| 平移 | 按住 Space，或选择 Pan |
| 适应画布 | F |
| 放大 / 缩小 | + / - |
| Approved / Needs review / Excluded | 1 / 2 / 3 |
| 撤销 | Ctrl+Z or ⌘Z |
| 重做 | Ctrl+Shift+Z or ⌘Shift+Z |
| 保存 | Ctrl+S or ⌘S |
| 查看快捷键 | ? |

## 8. 前后端分开部署

在保存图片、标签及模型的电脑上：

```sh
annodesk api --host 0.0.0.0 --port 8765 --models-config /config/models.json
```

在提供前端页面的电脑上（同样安装基础 wheel）：

```sh
annodesk ui --api-url http://gpu-host:8765 --port 8080
```

浏览器打开 `http://前端电脑:8080`。如果需要让其他电脑访问前端，请为 `ui` 增加 `--host 0.0.0.0`。`gpu-host` 必须能从浏览器所在电脑访问。

所有数据路径、模型配置和 `HF_MODELS` 以 API 电脑为准，浏览器电脑上的目录不会自动上传。当前版本没有认证，HTTP 部署限于可信网络。

## 9. 常见问题

| 现象 | 处理方式 |
| --- | --- |
| 升级后样式丢失、请求旧 CSS / JS 404，或只有某个浏览器异常 | 先保存编辑，重启为新版本后强制刷新（Windows / Linux：Ctrl+Shift+R；macOS：⌘Shift+R）；必要时只清除此站点的缓存。不同浏览器的缓存相互独立 |
| 页面提示 Open project | 打开数据集，或启动时传入 `--project`；不表示服务故障 |
| 端口占用 | 换一个 `--port`，或停止原来的服务 |
| 模型显示 missing | 检查 JSON 路径、目录解析、backend 和目录顶层权重；点击 Reload |
| 提示 No compatible .pt checkpoint | 当前适配器不兼容该目录内容；准备兼容权重，不会自动下载或转换 |
| Multiple checkpoint candidates | 为每个模型使用独立目录，避免多个候选权重 |
| 缺少 ultralytics / torch / tokenizer | 在后端环境手动安装对应依赖；运行 `annodesk doctor` 辅助检查 |
| 保存冲突 | 保留页面和备份，核对是否有其他进程或工具修改同一项目；不要强行覆盖 |
| 推理完成时已有新编辑 | 页面会保留新编辑并提示需要核对；备份后比较结果，再决定如何重新载入 |
| 导出结果少于图片数 | 检查当前任务的审核状态、Excluded、未分配类别和空标签确认 |
| 模型不支持或推理异常 | 基础框标注仍可用；记录模型格式、依赖版本和控制台错误进行排查 |

## 10. 查阅已安装的指南

```sh
annodesk docs
annodesk docs --output ./AnnoDesk-user-guide.md
annodesk --help
annodesk segment --help
```

`annodesk docs` 输出随当前安装版本发布的本指南；`--output` 导出 Markdown，目标文件已存在时不会覆盖。升级安装包后，可用该命令获取对应版本的说明。

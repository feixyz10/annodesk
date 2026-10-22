# AnnoDesk 用户指南

AnnoDesk 用于标注图像中的检测框和实例分割 mask，可导入已有 YOLO 检测标签，再根据框生成分割结果并人工复核。界面支持英文和简体中文，采用浅色主题，在浏览器中使用；图片、模型和标注数据保存在运行后端的电脑上。

本指南对应 0.4.0。

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
python -m pip install ./annodesk-0.4.0-py3-none-any.whl
```

基础安装即可使用框标注、类别、审核状态和数据管理。若需要 SAM 或检测模型推理，显式安装可选依赖：

```sh
python -m pip install "./annodesk-0.4.0-py3-none-any.whl[inference]"
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

同一数据集只允许一个 AnnoDesk 写入进程。后端打开项目期间持有跨进程写锁，独立 `segment` / `detect` / `boxes-from-masks` 命令不能同时写同一项目；先关闭项目服务。异常退出后系统会释放锁，不需要删除 lock 文件。不要在多个 Uvicorn worker 中运行同一项目。

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

## 4. 配置本地模型

创建自己的 `models.json`，例如：

```json
{
  "default_model": "sam2-small",
  "default_detection_model": "detector",
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
    },
    {
      "id": "detector",
      "name": "My detector",
      "backend": "ultralytics",
      "task": "detection",
      "source": "/srv/models/my-detector"
    }
  ]
}
```

- `id`：唯一标识，供 `--model` 和默认模型引用。
- `name`：页面显示名称。
- `backend`：`sam`、`sam2`、`mobile_sam`、`sam3`，检测使用 `ultralytics`。
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

建议始终显式传入自己的配置文件。画布工具栏的模型入口打开居中 **Model settings** 窗口，分 Detection / Segmentation。**Available** 表示目录/权重可用，**Loaded** 表示交互执行器已加载，二者不同。**Reload** 重新读取配置，**Check classes** 检查检测类别兼容，**Load** 显式加载到所选设备；**Apply** 保存项目/模型参数，**Cancel** 丢弃未应用参数，但不会撤销已经执行的 Load。悬停不展示路径，主动展开 Diagnostics 或运行 CLI 可查看详细错误。模型目录存在不代表依赖已安装。

### 检测类别与项目兼容

标准 Ultralytics 检测 `.pt` 通常带有类别名称（参见[官方预测说明](https://docs.ultralytics.com/modes/predict/)）。缺少可靠名称或只有 `class_0` 等占位名时，在模型条目中增加 `"classes_file": "detector-classes.yaml"`，例如：

```yaml
names:
  0: cat
  1: dog
```

也支持 JSON 的 `names` 数组/字典。文件相对 `models.json` 解析，也可绝对路径，不使用 `HF_MODELS` 回退；模型类别必须为连续的 `0..nc-1`。权重和文件都有可靠名称时必须完全一致，文件不能覆盖真实类别。仅含 state_dict 的任意第三方模型文件不保证可加载。

模型和项目的 `(ID, name)` 必须完全一致，或任一集合是另一集合的子集。任何冲突都报错，不自动重映射 ID 或忽略大小写。导入现有 YOLO 数据时应提供正确的 `data.yaml`，占位名称不会自动等同于真实类别。

**Allow new classes from this model** 默认关闭：丢弃超出项目的检测类别；开启时只在某张图片的检测结果通过筛选且保存成功后才引入实际出现的类别，保持原模型 ID。可从空项目开始，但关闭该开关且没有可接收类别会报错。此设置按项目/模型保存。检测批任务运行期间请等待任务结束后再新增、改名或重排项目类别，颜色仍可调整。

工作类别 ID 可有空洞，重新打开不会补齐。这样的 `data.yaml` 不保证可直接训练；使用 Export 生成连续 ID 的训练副本和 `class-id-map.json`，工作项目保持不变。

## 5. 在页面中标注

### 界面语言

右上角语言下拉框可在 **English / 简体中文** 间即时切换。首次默认英文，选择会保存在当前浏览器站点中，刷新或重新打开后保留；浏览器禁用本地存储时仍可切换，但关闭后可能不保留。不同设备和浏览器可独立选择，无需重启服务。下文保留英文按钮名称以便对照。

工具栏、窗口、审核状态、提示和快捷键说明随语言切换；快捷键映射本身保持不变，中文输入法组合输入期间不触发单键操作。类别名、自定义标签名、模型名/ID、路径和原始诊断/日志保持原文，不更改项目数据。界面语言不会改变文本提示模型支持的语言；当前文本提示输入仍按模型要求使用英文。

### 浏览图片和设置类别

左上图片列表支持 **Tree / Flat**、搜索和展开目录；底部缩略图可左右滚动，图片按需加载。拖动面板之间的分隔条可调整比例。

左下 **Class palette** 是赋类入口：

- 没有选中实例时，点击类别设置新标注的默认类别。
- 点击 **Default class** 取消实例选择，回到默认类别设置。
- 选中框或 mask 后，点击类别直接修改该实例。
- 按 **C** 打开类别搜索，↑↓ 选择、Enter 确认、Esc 取消；选择模式下双击实例也可打开。

顶部 **Classes** 用于增加类别、修改名称和颜色。类别 ID 平时保持稳定；**Reindex IDs…** 会修改整个项目的类别映射和标签文件，使用前备份项目。

### 画框和生成 mask

1. 在 Class palette 中选择类别。
2. 使用 **Draw box** 拖出检测框，切回 **Select** 后可移动和拖动控制点调整；右侧也可编辑坐标。
3. 选中框后按 Enter，或点击 **Refine mask**，使用当前模型生成 mask。
4. 模型选择旁的 **Segment current** 处理当前图片中尚无 mask 的未锁定检测框。

仅需要 mask、不希望保存检测框时，使用 **Box prompt: mask only**，或用正负点建立提示，再执行分割。框提示与显式检测框分开保存。正点用于包含区域，负点用于排除区域。文本提示工具只适用于支持文本提示的 SAM 3 模型，需先设置默认类别。

开启 **Auto-segment** 后，切到含待处理检测框的图片会自动分割。切换到 Detection 时可使用 **Detect current** 和 **Auto-detect**（默认关闭），后者仅对 Not reviewed、未排除且没有实例的图片自动检测。

**Batch…** 打开批量配置，选择 Detect boxes、Segment existing boxes 或 Boxes from masks；范围可为全项目或当前搜索结果。默认只处理目标任务的 Not reviewed，可显式加入 Needs review / Approved；Excluded 始终跳过。检测和 mask 转框按 Detection 状态，SAM 按 Segmentation 状态。**Preview scope** 只读检查范围，显示各类跳过和损坏输入数量；检测还会检查类别兼容。开始时重新验证并冻结配置/范围。设备和 worker 规则见第6节。

任务启动自动打开居中 **Tasks** 非模态窗口，约900px，可调整大小；关闭只收起，标注和后台任务继续，顶部保留 `Tasks ◌ 60/75` 和细进度线。窗口显示完整进度、开始时间/耗时、成功/失败/跳过/剩余、检测框与新增类别数量、参数快照、worker 当前图片及错误。扫描、模型加载、最终导出阶段显示不定进度动画，不伪造百分比。统计栏始终常驻。

取消停止新派发，在途图片保存后生效。恢复延续原范围和模型/设备/参数快照，只处理 remaining；权重或类别表变化需要新建任务。排队期间若图片已被人工改为不符合筛选条件，会拒绝处理并记入失败，保留人工审核。失败图片在修复原因后另建批次重试。结束通知不抢焦点，断开浏览器不会取消任务，Logs 仍在独立右侧抽屉。

进度的 `finished = succeeded + failed`，分母排除跳过项；成功只在标注保存后计数。例如 `60/75 finished · 58 succeeded · 2 failed · 25 skipped` 仍有15张未处理。启动失败只报告一次任务错误，不把整个数据集伪装成逐图失败。

选中实例可在右侧删除、锁定或隐藏。锁定后先解锁才能改类；隐藏只影响显示，不等于从导出中移除。画布支持滚轮局部缩放；右上角集中放置 **Pan**、缩放与 **Fit image**，平移不放在左侧标注工具栏。Pan按钮可切换，按住Space也可临时平移。

### 自动生成检测框

Detection 模型设置支持 Confidence、NMS IoU、Image size、Max detections、模型类别筛选和设备。默认 **Empty images only**，已有任意实例时不处理；显式选择 **Append with duplicate checks** 才允许追加，按同类别 IoU≥0.7 跳过重复框，保留已有人工框和 mask。置信度保留在内部实例中，YOLO txt 不增加额外列。生成新框后 Detection 变为 Not reviewed；没有检测结果不自动确认空背景。

选中 mask 后右侧 **Create box from mask** 可生成同一实例的框；已有框可用 **Recalculate box** 显式替换。当前图片 **Create missing boxes** 与批量 Boxes from masks 默认只补缺框，跳过锁定实例。此操作只做 CPU 几何计算，不加载模型，保留 mask/类别/实例 ID，只重置 Detection 审核。以后修改 mask 不会自动同步框，需主动重算；普通 SAM mask-only 标注仍不保存框。

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

顶部常驻统计栏按当前 detection / segmentation 任务汇总全项目，不受左侧搜索影响。`Reviewed = Approved + Needs review + Excluded`；四类数量互斥，相加等于总图片数。Excluded 优先，取消排除后恢复原审核状态。自动生成 mask 不增加 Reviewed。统计以成功保存的状态为准；首次构建显示 Loading statistics，空项目显示 No images。`.annodesk/statistics.sqlite3` 是可重建缓存，不是标注真值。

图片可添加自定义 tags（逗号分隔）和 notes。顶部 **Tags** 抽屉展示只读的四个内置审核状态，下方管理自定义 tag 名称和颜色。当前自定义 tag 改名不会批量迁移旧图片上的 tag 字符串，需自行核对。

### 导出

先选中 detection 或 segmentation 任务并完成复核，再点击 **Export**。当前页面导出当前任务的 YOLO 数据集，不是只导出当前图片。

默认跳过未审核、Needs review、Excluded 和含未分配类别实例的图片；无对象图片需明确勾选 **Confirm no objects for this task** 并复核通过，才能作为空标签样本导出。

导出同样自动打开 Tasks 窗口，收起后由顶部轻量入口显示进度，按已检查图片数推进，最终写报告阶段显示动画。取消后删除本次不完整导出。完成后结果位于后端项目的 `.annodesk/exports/<id>/`，Tasks 显示路径；当前导出为目录，不额外压缩成归档。导出目录包含复制的图片、标准 `labels/`、类别配置及报告；分割工作目录中的 `labels_seg/` 在导出副本中转换为标准 `labels/`。`class-id-map.json` 记录工作数字 ID 到导出 ID 的对应。导出类别 ID 会连续重排，工作项目不受影响。

YOLO polygon 对孔洞等结构可能有损，请保留原始项目及内部 RLE。当前界面还没有 COCO 导出选项和回收站管理界面。

## 6. 不打开页面，直接将检测框批量分割

```sh
annodesk segment --project /data/my-dataset --models-config ./models.json --model sam2-small
```

省略 `--model` 使用 JSON 中的 `default_model`。该命令不启动 HTTP 服务或浏览器。

- 保留 detection 框及类别，分割写入 `labels_seg/`，内部保存无损 RLE。
- 默认只处理 Segmentation 的 Not reviewed；跳过已有 mask、锁定实例和 Excluded 图片。
- 可用 `--review-states pending uncertain ok` 显式扩大审核范围，不授权覆盖人工结果。
- 每张图片独立保存；中断后再次运行可跳过已完成结果。
- 控制台显示任务阶段和汇总；执行计划及逐图结果位于 `.annodesk/segment-report.json`。
- 第一次 Ctrl+C 停止派发并保存当前在途结果；第二次强制终止。未保存的结果不会算成功。
- 退出码：0完成且无单图失败；1存在单图失败；2配置/设备/启动失败；130取消/中断。

生成结果仍需在页面人工复核，命令不会自动标为 Approved。

### 无界面检测与 mask 转框

```sh
annodesk detect --project /data/my-dataset --models-config ./models.json \
  --model detector --allow-new-classes --confidence 0.3 \
  --device-type cuda --devices 0,1 --num-workers 3
annodesk boxes-from-masks --project /data/my-dataset
```

检测默认只处理 Detection 的 Not reviewed 且没有实例的图片；`--write-policy append` 显式追加，`--model-classes 0 1` 筛选模型类别，阈值/IoU/尺寸/最大检测数可配置。报告为 `.annodesk/detect-report.json`。`--model` 始终是配置 ID，不是权重文件名。

mask 转框不需要可用模型或 Torch；`--recalculate-boxes` 允许替换未锁定框。报告为 `.annodesk/boxes-from-masks-report.json`。两者均支持 `--review-states pending uncertain ok`；默认只有 pending。退出码、项目锁、日志、取消语义与 segment 相同，详细选项见对应 `--help`。

### 设备与 worker

```sh
CUDA_VISIBLE_DEVICES=2,5 annodesk segment --project /data/my-dataset \
  --models-config ./models.json --model sam2-small \
  --device-type cuda --devices 0,1 --num-workers 3
```

`--device-type auto|cuda|cpu|mps` 默认 auto，依次选择 CUDA、MPS、CPU；显式选择不可用硬件会报错，推理失败不自动改用 CPU。`--devices auto` 默认 CUDA 全部可见设备，`0,1` 是经 `CUDA_VISIBLE_DEVICES` 过滤后的逻辑编号，上例对应宿主机2、5。CPU/MPS 只接受 auto。

`--num-workers auto` 默认每个选中 CUDA 设备1个，CPU/MPS为1个；也可填写正整数。3个 worker/2个设备依次分配为 `cuda:0, cuda:1, cuda:0`，每个 worker 常驻一份模型。同一设备多个 worker 会增加显存占用，并不保证更快。少于设备数时只使用前几个设备，日志会提示闲置设备。CPU 有线程预算；MPS 多进程和真实 CUDA 性能仍需在目标机器验证。

### 日志

`serve`、`api`、`ui`、`segment`、`detect`、`boxes-from-masks` 为每次运行创建日志，默认 `~/.cache/annodesk/YYYY-MM-DD_HHMMSS_ffffff.log`（包括 macOS）。可通过 `--log-dir /path/to/logs --log-level DEBUG` 修改目录和文件/终端等级，默认 INFO，20MB轮转，保留14天。目录不可写时会警告并继续使用终端与内存日志，不影响标注保存。查询 help/docs/doctor/models 不创建日志文件。

页面 **Logs** 抽屉宽度可拖动，未打开项目也可用。显示时间、等级和重要信息，包含模型、设备、worker READY、任务状态及错误，没有源码文件名/行号和 traceback。选择 Service 或 Current project；等级可切换 `=`（仅该等级）或 `≥`（该等级及以上），包括 SUCCESS。支持暂停/恢复、自动滚动开关、清空视图、复制当前视图和下载当前日志文件。普通轮询、逐框推理和 autosave 不刷屏，同类错误会合并显示，文件和报告保留原始错误。

页面只保留最多1000条，服务环形缓冲2000条，过期缺口会提示。暂停/关闭抽屉不会停止任务或日志写盘。分机部署时文件在后端电脑；单独运行的 CLI 有自己的会话文件，不自动混入另一个后端的实时 Logs。UI-only 进程的日志在其本地文件中查看，页面 Logs 连接的是所配置 API。

## 7. 快捷键

输入框、类别搜索和 IME 输入期间不会触发工作台单键快捷键。页面右上角 **?（Shortcuts）** 可搜索快捷键；按钮提示约 150ms 后显示。

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
| Project is in use | 关闭占用该项目的另一个 AnnoDesk 服务/CLI；不要删除锁文件强行绕过 |
| 任务加载失败/显存不足 | 查看 Logs 和 Tasks，减少 workers 或选择更小的模型后新建批次；不会静默换设备 |
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
annodesk detect --help
annodesk boxes-from-masks --help
```

`annodesk docs` 输出随当前安装版本发布的本指南；`--output` 导出 Markdown，目标文件已存在时不会覆盖。升级安装包后，可用该命令获取对应版本的说明。

# AnnoDesk 设计规范

版本：1.0 · 2026-10-22。本文合并此前讨论，是实现与验收的唯一设计依据；旧草案与交互原型仅供历史参考。

## 1. 产品目标

面向图像数据集的本地优先标注工具，支持检测框和实例分割。从纯图片开始标注，或直接打开 Ultralytics YOLO 框数据集，以 SAM 按框预分割，再人工修改与复核。首版是英文、浅色 Web 工作台；未来可复用前端以 Tauri 包装客户端。

支持单机运行及前后端分机部署。首版不做账号、权限、TLS、多人协作、视频、训练。不要把“浏览器与后端分机”与“本机数据、远端独立推理节点”混为一谈：后者不属于首版。

## 2. 技术与仓库

- 前端：Vue 3、TypeScript、Vite、Pinia、Naive UI。Konva 管理框、提示点与选择；独立 Canvas 显示 mask，使用同一图像坐标变换。
- 后端：Python、FastAPI、Pydantic、Uvicorn；CLI 使用 tyro，通过类型化配置生成子命令，不自写 argparse，不使用 Typer。
- 模型：可替换适配器，首批目标为 SAM 2.1、MobileSAM、SAM 3；按能力启用正负点、框、文本。SAM 3 文本与视觉提示分开调用，不假设所有 SAM 衍生模型接口相同。
- 项目根是一个 uv 项目、一个 Python distribution，名称/import/命令统一为 annodesk。使用 src/annodesk、frontend、tests、docs/specs。
- uv sync 安装 Python 环境；uv.lock 固定依赖。Python 基准采用当前已配置的 3.13，基础标注服务验证该版本；推理 extras 如不兼容，明确要求另选受支持 Python，而不悄悄更改用户解释器。
- 可选模型依赖 lazy import；基础安装即可使用 UI、框标注与数据管理，安装 inference extra 后准备真实推理。模型权重不随 wheel 发布，也不由 uv sync 暗中下载。
- Python 用 ruff format、ruff check（E/F/I/UP/B）统一格式与检查；每次代码提交前执行。领域/存储/API 用 pytest，前端用 vue-tsc、Vite 构建及关键交互验证。
- Git 跟踪源码、测试、锁文件、正式设计及必要 README；忽略计划、执行记录、旧草案、截图、交互原型、环境、缓存、模型与用户数据。

## 3. 工作项目与路径

标准布局：

```text
dataset/
  images/[train|val|test]/任意多级目录/image.jpg
  labels/对应相对目录/image.txt          # detection
  labels_seg/对应相对目录/image.txt      # segmentation
  data.yaml
  .annodesk/
    project.json
    annotations/对应相对路径/image.jpg.json
    masks/实例UUID/版本.png
    operations/
    trash/
```

不要求 train/val/test 齐全，也不要求目录必须取这些名字。图片可以直接位于 images 下；平铺/多级目录均可。标签相对路径必须镜像图片目录。图片支持 jpg/jpeg/png/webp/bmp/tif/tiff。

提供两种入口：打开数据集根（识别 images 和可选标签），或打开任意纯图片目录（项目记录图片根映射，不移动原图）。后端处理本机路径，浏览器不把客户端路径误当作后端路径。

同目录同 stem 不同扩展名会映射到同一个 YOLO txt；导入必须报告冲突，不覆盖。非法标签行、类别越界、尺寸异常应展示具体文件和原因，不能静默丢弃。没有 txt 不等于人工确认背景。

data.yaml 可缺失。扫描已有类别数字 ID 时生成 class_N 占位名；新增类别自动维护 names 和项目类别表。未划分数据允许标注，不伪造 val/test；训练导出前再完成划分校验。

内部 JSON/无损 mask 是完整编辑记录；两个 txt 目录是同步的 YOLO 投影。首次从 txt 初始化；之后检测外部修改并明确要求重新导入/冲突处理，不自动覆盖用户外部修改。

## 4. 实例和分类

每个实例有稳定 UUID、类别 UUID、可选显式 box、可选 mask、来源、提示历史和模型标识。box-only、mask-only、box+mask 均合法。数字 class ID 只用于序列化。

- Draw box：产生显式检测框，可拖动、四角/边缩放、数值调整、键盘微调、改类、删除、隐藏、锁定、撤销/重做。限制图像边界，禁止零面积或非有限坐标。
- Box prompt：框只是分割提示，默认只保存 mask。正负点或文本分割也不自动创建 detection box。
- 从已有检测框生成 mask：关联原实例、继承类别、保留框。调整框后关联 mask 标需复核，提供按新框重算；不静默覆盖人工 mask。
- 选中已有实例加正负点，接受后替换同一实例 mask；不新增重复对象。重启后可从提示历史重建，不依赖持久化 logits。
- SAM 3 文本可返回多个实例；先指定类别和提示词，预览后接受。中文类别名称允许；不承诺模型中文提示质量。
- 删除操作区分仅 box、仅 mask 和整个实例；按当前明确的几何选择执行。无损 mask 保留孔洞和不连通部分，投影多边形不作为唯一数据。

类别面板常驻左下。没有选中实例时，显示 Default for new annotations: <class> 并设置新对象默认类别；选中实例时显示 Class for selected object(s)，点击类别改类。Default class 按钮明确取消选中，并以 tooltip 解释它只设置后续标注的类别。多类别支持搜索、最近使用和收藏；未分配类别草稿允许存在，但完成/导出前必须解决。

## 5. 类别、tag、颜色

类别支持新增、重命名、颜色编辑、删除；新增分配递增 ID，不复用已删除 ID。删除仍被引用的类别必须选择改派或删除实例。内部身份始终不变，ID 空缺在工作配置中保留占位。

提供一键连续编号，先预览旧/新 ID 映射和影响数量。获得项目写锁，暂停推理写入，更新当前项目 labels/**/*.txt、labels_seg/**/*.txt、data.yaml 和内部映射。只改标注行首 ID，不改坐标、图片路径清单或历史导出副本。全量预校验、备份、事务日志和启动恢复保证多文件一致；不把多次 rename 称为跨文件原子操作。

class 与自由 tag 分别管理调色板，采用同一策略：默认建议颜色，可手动改色；新颜色尽量远离同一调色板已用色。在 OKLab 中从明度/色度适中且落在 sRGB 色域的候选中，最大化到已有色的最小感知距离。不能用简单 RGB 距离替代，也不能保证无限类别仍可区分。

颜色绑定稳定 UUID，存项目字典；重命名、ID 重排和新增项不改变旧颜色。手动颜色过浅/过近时提示并提供替代色，但允许保留。颜色外保留名称、实例编号和选中描边；tag 用淡背景、色边、深色正文。状态色固定，不作为可编辑 tag 色。

## 6. 图片状态与清理

Detection 和 Segmentation 分别记录复核状态，图片另有全局使用状态。英文展示：

| 展示 | 内部含义 | 颜色 |
| --- | --- | --- |
| Not reviewed | pending，尚未检查 | 灰 |
| Approved | ok，人工确认 | 绿 |
| Needs review | uncertain，有疑问/发现问题 | 琥珀 |
| Excluded | usability=discard，排除使用 | 低饱和红 |

Excluded 优先显示但保留原复核状态，不等于删除。blurry、night、occluded 等是自由多选 tag，可新增、改色、备注、筛选、批量设置。

自动保存、自动分割不会变 Approved。修改已通过的任务标注使其回 pending；关联框变化使 mask 需复核，改 mask 不使独立检测框失效，共享类别变化影响两任务。Needs review 保持至人工明确处理。

清理 Excluded 前显示具体图片及标签数量，一起移入项目回收站，记录原路径，支持恢复；永久清空单独操作。默认批处理/训练导出排除 Excluded 和 Needs review，pending 是否导出由设置决定并显示计数。

## 7. 工作台布局

顶部：项目与连接、批处理、导出、Classes/Tags 管理、快捷键帮助。
左侧上方：图片搜索、状态筛选、Tree/Flat 文件列表；下方：常驻 Class palette。
中间：标注工具、模型选择/自动分割、主画布、文件与比例、横向缩略图带。
右侧：Current image，当前任务状态/tag、当前实例结果列表、选中实例属性及轻量显示设置。不得在当前结果下方混放全项目类别表。

左右分隔条可拖动，中心取剩余空间；默认左260px、右290px，最低左190px、右220px，保护中央可操作宽度。左侧上下也能拖动，分隔条支持键盘小步调整、双击复位。正式版记忆用户布局，窄窗口折叠侧栏，不强行压缩画布。

Tree 保留 images 下多级子目录，支持逐目录展开/收起、Expand all/Collapse all；Flat 展示文件名和相对父目录。折叠只影响树内可见行，不改变过滤序列；模式切换不改变当前图片。搜索匹配文件和路径，暂时展开匹配目录，清空后恢复。

实例列表与画布双向选择同步，包含短 ID、类别、Box/Mask、锁定/可见、推理和复核标记。Classes/Tags 抽屉仅管理项目字典，类别下拉与常驻面板允许快捷新增。

## 8. 画布与快捷键

视图工具使用放大镜 +/-、比例、手形 Pan、四角 Fit。滚轮以指针原图位置为中心缩放；按钮以中心缩放。Space 临时平移，松开恢复原工具。F 适应完整图片，1:1 表示原图像素与 CSS 像素一一对应，不能把 Fit 一律称为100%。缩放范围5%..3200%，保持少量图片可见。标注始终原图坐标，框线/提示点/控制柄保持可操作屏幕尺寸。

快捷键注册表为唯一来源，供命令执行、Tooltip、帮助抽屉共用；可搜索、修改映射、检测冲突和恢复默认。

| 操作 | 默认 |
| --- | --- |
| 上/下一图，下一待复核 | A / D，Shift+D |
| 选择，画框，正/负点 | V，R，Q / E |
| 框提示，文本提示 | B，T |
| 接受，取消 | Enter，Esc |
| 平移，Fit，专注 | Space拖动，F，Shift+F |
| 通过，有疑问，排除 | 1，2，3 |
| 类别1..9 | Alt+1..9 |
| mask/box显示 | M / H |
| 撤销/重做，保存 | Ctrl+Z or ⌘Z / Ctrl+Shift+Z or ⌘Shift+Z，Ctrl+S or ⌘S |
| 删除，快捷键帮助 | Delete/Backspace，? |

Tab 保留焦点导航。输入框、IME、浮层不触发画布单键；按钮焦点下 Enter/Space 保留正常行为。主要按钮 hover/键盘聚焦展示动作+按键；重要错误和不可用原因不只藏在 hover。

## 9. 缩略图和内存预算

横向缩略图可滚轮、触控板、拖动滚动条和左右按钮滚动。滚动不切图；明确选图才保存/切图。切图将当前项滚入可见区域，编辑状态/tag 不重置手动滚动。

- 虚拟列表，可见区两侧各预取3张，最多24个挂载节点；不是只给全量 img 加 lazy。
- 最大4个并发请求，窗口外待发任务丢弃，过期请求取消/响应丢弃。
- 应用解码 LRU 最多48张或24MiB，任一上限触发淘汰并释放引用/bitmap/Object URL；不声称可限制浏览器总内存。
- 按显示尺寸/DPR 请求，最长边上限320px；不向预览带传原图。
- 后端缩略图磁盘缓存默认512MiB，可配置。按内容指纹、尺寸和生成版本失效。
- 原图仅当前图按需加载，可预取下一张适当预览；超大图后续可扩展瓦片。文件列表虚拟化或分页。

## 10. 保存、并发和任务

编辑操作结束后短延迟自动保存；切图前强制提交并等待成功。失败保留当前编辑、显示重试，不带错切图。关闭页面有未保存内容则提示，不能指望 unload 完成写盘。

使用 revision 乐观锁及单写入会话，阻止多浏览器覆盖。保存内部记录、mask 和两类 txt 投影，以临时文件+原子单文件替换+操作日志恢复多文件一致性；全部完成才显示已保存。删除最后一个标注写空 txt，不残留旧标注。缺少标注与 explicit_empty 背景标记分开。

所有推理绑定 project/image/instance/prompt revision/model/job ID；过时结果不能覆盖人工编辑。后台批任务不依赖浏览器连接，完成逐图持久化，支持取消、失败重试、续跑；只在推理调用边界响应取消。

当前图、全部图、切图自动分割共用任务接口。默认只处理有框且无 mask 的实例，跳过 Excluded，不重算已编辑 mask。无框不自动猜目标/全图分割。交互请求优先，SAM 编码按图像指纹/权重/预处理缓存并有内存预算。

API 使用单 Uvicorn worker；模型由受控后台执行单元持有，推理不阻塞 HTTP。本地模型加载失败仍允许框标注。模型适配器提供 capabilities、load/unload、encode、segment_visual、segment_text，结果不直接写 UI 状态。

## 11. YOLO 与训练导出

默认工作投影为 YOLO。labels_seg 是工具约定，Ultralytics 默认从 images 映射 labels；仅在 YAML 添加 labels_seg 不能保证训练器采用。

导出 detection 或 segmentation 的独立 images/labels/data.yaml，分割输出将工作 labels_seg 转为标准 labels，禁止混放 box 与 polygon 行。保持多级路径，首版复制图片。检测默认只导显式 box，可选临时从 mask 推导，仅作用于导出，不回写工作项目。

导出校验类别、路径冲突、划分及未分配实例，可生成连续类别 ID 副本而不改工作项目。未标注不能当负样本，只有 explicit_empty 或完成标注的图像可纳入对应任务。

YOLO 多边形对孔洞/不连通实例可能有损，输出告警及报告；COCO RLE 支持无损导出。内部始终保留原始 mask、实例 ID 和提示历史。

## 12. CLI、构建与部署

单一 console script 使用 tyro：serve、api、ui、dev、build-ui、doctor、docs、models list、segment。CLI help 不加载模型；模型配置与项目标签分离，模型只从本地读取，禁止自动下载和推理时自动安装依赖。

```bash
uv sync
uv run annodesk serve --project /data/dataset --open
annodesk serve --host 0.0.0.0 --port 8765
annodesk api --host 0.0.0.0 --port 8765
annodesk ui --port 8080 --api-url http://gpu-host:8765
uv run annodesk build-ui
uv build
```

默认127.0.0.1:8765，仅 --open 打开浏览器，端口冲突报错。serve 同源提供 API+已编译 UI；api 仅后端；ui 只提供已编译资源和运行时 API 配置，不加载推理。数据集始终在后端机器，客户端本地图片需上传/同步/挂载后使用。

API /api/v1，info 返回应用/协议版本和能力；运行时 /ui-config.json 指定 API base，不写死 localhost、不重新编译。图片/mask/缩略图使用 ID URL，通过 HTTP 获取；跨源支持 CORS 和无 credentials 请求。SSE/任务轮询恢复按 job ID，不丢持久状态。

Hatchling 打包。web_dist 作为 package data 随 wheel/sdist 发布，普通运行者不需 Node。仓库跟踪匹配的预构建资源，干净 clone 后 uv sync 即可打开 UI；前端开发使用 Node/npm lock，build-ui 执行 npm ci、类型检查、构建。uv sync 不隐式安装 Node 或 npm。发布 CI 先重建前端并检查资源版本，再 uv build，并在新环境安装 wheel 验证。安装目录只读或任意 cwd 均正常。

### 12.1 本地模型配置与无界面分割

仓库提供 models.json；命令行 --models-config 优先，其次 ANNODESK_MODELS_CONFIG、当前目录 models.json、仓库默认、wheel 内置默认。JSON 定义 default_model 及 models 数组，每项含 id、name、backend(sam/sam2/mobile_sam/sam3)、source（模型最终一级目录，不配置 checkpoint 文件名）。ID 唯一，默认 ID 必须存在。

source 只填写最终一级模型文件夹，不填写 pt/safetensors 文件，也不提供 checkpoint 字段。展开环境变量和 ~ 后统一两步查找，不识别 repo ID 类型：先相对 JSON 目录 resolve 并检查 is_dir；不是目录则检查 $HF_MODELS/source（HF_MODELS 已设置时）。绝对路径直接检查目录，缺失报错，不剥离根路径后回退。repo ID 与普通相对目录的查找规则相同；本地同名文件不视为目录。

适配器在已选目录内自动查找兼容 .pt 权重，先按 backend 的已知命名匹配；无已知命名时仅接受唯一 .pt。没有兼容权重或多个候选均报错，不根据文件缺失再次换目录。safetensors-only 的 HF 目录暂不被当前 Ultralytics 适配器支持，页面明确显示不可用。配置每个 source 只包含一个模型。禁止 URL 和自动下载；推理禁用库联网/自动安装选项，Python 推理线程审计网络连接和下载/安装进程。辅助资源缺失也直接报错。

GET /api/v1/models 无需打开项目，返回配置条目、默认 ID、本地可用性、解析路径、错误、文本能力；页面模型选择器从此加载，可 Reload 配置及可用性。选择缺失模型时明确报错。GET /api/v1/project 在未打开项目时返回 200 null，避免把正常初始状态记录成 409；依赖项目的实际操作仍可返回 409。

annodesk segment --project /data/dataset --models-config ./models.json --model <id> 同步处理已有 YOLO 框，不启动 UI 或 HTTP 服务。默认模型来自 JSON，跳过已有 mask、锁定对象及 Excluded 图片；逐图保存到 labels_seg 与内部 RLE，保留 detection 框及类别 ID。中断后再次运行跳过已成功结果；失败明细写入 .annodesk/segment-report.json，失败退出码为 1，成功为 0。输出待人工复核，不自动标为 Approved。

## 13. 验收和分模块实施

以可运行模块依次提交：工程/CLI；领域和YOLO存储；API和保存；Vue工作台；推理适配/任务；类别迁移/清理/导出；集成和发布验证。未完成能力必须在 UI 显式不可用或在 README 说明，禁止用模拟推理假装真实模型。

关键验收覆盖：YOLO多级路径和冲突、缺少YAML、类ID稳定与迁移、box/mask-only语义、切图保存失败与过时推理、无损mask往返、Excluded恢复、不同origin图片/保存/任务、wheel静态资源及tyro入口、缩略图预算、画布坐标/缩放、快捷键焦点/IME。提交前运行ruff和相应测试，前端提交还需类型检查/构建。

## 14. 设计自检记录

- 已消除多份草案的名称/CLI差异，采用AnnoDesk、tyro、light/English。
- 已区分类别管理与标注赋类、自由tag与固定状态、框标注与框提示、工作labels_seg与训练labels。
- 已区分uv依赖、Node构建、权重准备，避免承诺所有模型自动安装或GPU驱动自动配置。
- 已定义多文件恢复、外部修改、未标注/背景和同stem冲突，不以YOLO txt充当全部编辑数据。
- Python基准遵循用户现有3.13配置；真实推理兼容性必须实测，基础标注不依赖GPU安装成功。

### 交互细化：赋类、提示和品牌图标

Class palette 为日常赋类入口；顶部 Manage classes 为名称、颜色、ID 管理入口。选中框或 mask 后可直接点左侧类别，或按 C 打开带搜索的类别选择器，以 ↑↓ 选择、Enter 确认、Esc 取消。画布选择模式下双击实例也可打开；右侧提供 Change class 按钮。赋类沿用自动保存/撤销，不修改几何，锁定实例不可赋类。1/2/3 仍用于图片审核状态，不与类别快捷键混用。

全局提示约 150ms 后显示，适用于 pointer hover 及键盘 focus，替代浏览器无法控制延迟的 title 提示。提示展示作用及已有快捷键，离开、点击、滚动、Esc 时关闭；窗口边缘自动调整位置。图标采用同一份 SVG：蓝色标注框与白色 mask 轮廓，复用为 favicon 与左上角品牌标识。

Tags 抽屉顶部始终展示四个内置审核状态及固定颜色/含义（Not reviewed、Approved、Needs review、Excluded），标注 Read only，不提供改名、改色或删除控件。下方独立 Custom image tags 分组管理自定义标签；内置项不写入可编辑 tags 字典。审核前三项按任务记录，Excluded 仍为整图标记，二者语义不变。

快捷键补充：X 或 Delete 删除当前选中标注；←/→ 与 A/D 均可前后切图。沿用输入框、IME、弹层与锁定实例的快捷键保护，帮助抽屉、删除按钮提示与状态栏保持同步。

快捷键文案约定：同一功能的替代操作使用 or（例如 X or Delete、C or double-click），不同功能依次对应的按键使用 /（例如 Previous / next image 对应 A / D or ← / →）。撤销与重做分行展示，避免组合键歧义。

面向安装包用户的操作说明保存于 docs/user-guide.md，与开发者 README 分离。该指南作为 package long description 并以 annodesk/docs/user-guide.md 资源随 wheel 发布，sdist 同时包含源文档；annodesk docs 输出当前安装版本指南，--output 导出 Markdown 且拒绝覆盖已有文件。

入口 HTML（含 /index.html）与状态 JSON 使用 Cache-Control: no-store；HTML 不使用旧 ETag/Last-Modified 条件请求返回 304，以免升级后仍引用已移除的 hash 静态资源。客户端配置和 API fetch 同样显式 no-store。未打开项目时仍由前端空状态分支停止拉取图片列表，不将 409 改为空数据掩盖错误。

# AnnoDesk 设计规范

版本：1.3 · 2026-10-22。本文及明确链接的版本增补合并此前讨论，作为实现与验收的设计依据；旧草案与交互原型仅供历史参考。

0.2.0 实现 §10.1 多 worker、§10.2 日志及 §10.3 审核统计与任务抽屉。已发布的0.1.0不包含这些新增能力；实际GPU/SAM权重验证与下文尚未实现的完整产品目标分开记录。

0.3.0已实现扩展详见 [自动框、类别校验与模型/任务窗口](assisted-boxes.md)。该增补已获用户确认，本轮相关条款优先于本文0.2右侧Tasks抽屉等历史设计；审核统计始终常驻。

## 1. 产品目标

面向图像数据集的本地优先标注工具，支持检测框和实例分割。从纯图片开始标注，或直接打开 Ultralytics YOLO 框数据集，以 SAM 按框预分割，再人工修改与复核。首版是英文、浅色 Web 工作台；未来可复用前端以 Tauri 包装客户端。

支持单机运行及前后端分机部署。首版不做账号、权限、TLS、多人协作、视频、训练。不要把“浏览器与后端分机”与“本机数据、远端独立推理节点”混为一谈：后者不属于首版。

## 2. 技术与仓库

- 前端：Vue 3、TypeScript、Vite、Pinia、Naive UI。Konva 管理框、提示点与选择；独立 Canvas 显示 mask，使用同一图像坐标变换。
- 后端：Python、FastAPI、Pydantic、Uvicorn；业务日志采用 Loguru；CLI 使用 tyro，通过类型化配置生成子命令，不自写 argparse，不使用 Typer。
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
| Excluded | excluded=true，排除使用 | 低饱和红 |

Excluded 优先显示但保留原复核状态，不等于删除。blurry、night、occluded 等是自由多选 tag，可新增、改色、备注、筛选、批量设置。

自动保存、自动分割不会变 Approved。修改已通过的任务标注使其回 pending；关联框变化使 mask 需复核，改 mask 不使独立检测框失效，共享类别变化影响两任务。Needs review 保持至人工明确处理。

清理 Excluded 前显示具体图片及标签数量，一起移入项目回收站，记录原路径，支持恢复；永久清空单独操作。默认批处理/训练导出排除 Excluded 和 Needs review，pending 是否导出由设置决定并显示计数。

## 7. 工作台布局

顶部以间距和细分隔线分组：左侧项目/Open与Classes/Tags；Batch/Export为处理组；Tasks/Logs为右侧任务诊断组；最右侧为快捷键帮助图标。Tasks按钮预留状态宽度，运行中的数字与旋转标识在按钮内部，不推动邻近按钮。当前图操作随Detection/Segmentation切换，模型入口打开居中设置窗；Reload等详细设置移入该窗。顶部工具栏下增加常驻项目审核统计栏，详见 §10.3。
左侧上方：图片搜索、状态筛选、Tree/Flat 文件列表；下方：常驻 Class palette。
中间：标注工具、模型选择/自动分割、主画布、文件与比例、横向缩略图带。
右侧：Current image，当前任务状态/tag、当前实例结果列表、选中实例属性及轻量显示设置。不得在当前结果下方混放全项目类别表。

左右分隔条可拖动，中心取剩余空间；默认左260px、右290px，最低左190px、右220px，保护中央可操作宽度。左侧上下也能拖动，分隔条支持键盘小步调整、双击复位。正式版记忆用户布局，窄窗口折叠侧栏，不强行压缩画布。

Tree 保留 images 下多级子目录，支持逐目录展开/收起、Expand all/Collapse all；Flat 展示文件名和相对父目录。折叠只影响树内可见行，不改变过滤序列；模式切换不改变当前图片。搜索匹配文件和路径，暂时展开匹配目录，清空后恢复。

实例列表与画布双向选择同步，包含短 ID、类别、Box/Mask、锁定/可见、推理和复核标记。Classes/Tags 抽屉仅管理项目字典，类别下拉与常驻面板允许快捷新增。

## 8. 画布与快捷键

视图工具集中在画布右上角：手形 Pan、放大镜 +/-、比例、四角 Fit；Pan不放在左侧标注工具栏。Pan按钮可切换进入/退出平移，Space保留临时平移。滚轮以指针原图位置为中心缩放；按钮以中心缩放。Space 临时平移，松开恢复原工具。F 适应完整图片，1:1 表示原图像素与 CSS 像素一一对应，不能把 Fit 一律称为100%。缩放范围5%..3200%，保持少量图片可见。标注始终原图坐标，框线/提示点/控制柄保持可操作屏幕尺寸。

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

### 10.1 多进程推理与设备分配（0.2.0）

CLI segment 与页面 Batch 共用执行层。当前图交互分割保留独立串行通道，不等待整个批次完成；不抢占在途图片，也不保证独立模型在同一GPU上具有硬件调度优先级。不在多个进程之间分拆同一图像的提示。

| 参数 | 取值 | 默认与约束 |
| --- | --- | --- |
| --device-type | auto、cuda、cpu、mps | auto 按 CUDA → MPS → CPU 选择；显式类型不可用报错 |
| --devices | auto 或逗号分隔逻辑编号，如 0,1 | CUDA 默认全部可见设备；CPU/MPS 只接受 auto |
| --num-workers | auto 或正整数 | auto：CUDA 每个选中设备1个，CPU/MPS 为1个 |

--model 仍为 models.json 中的 ID，不是权重路径。UI、CLI 共用 ModelRegistry：先选择 ID，再解析 source 目录和兼容权重，禁止自动下载。运行时设备参数放在 CLI/任务配置，不混入模型目录字典。

CUDA_VISIBLE_DEVICES 由启动环境设置，程序不覆盖它。--devices 使用该环境过滤和重排后的逻辑编号；例如 CUDA_VISIBLE_DEVICES=2,5 配合 --devices 0,1，分别对应被暴露的原始设备2、5。记录原环境值与逻辑编号映射，不将逻辑编号再次当作宿主机编号解析。device-type=auto 配合数字设备列表时要求 CUDA；不可用则报错，不忽略该列表。拒绝重复、负数、越界或空项。只在 auto 且 devices=auto 时允许硬件选择回退；模型推理失败不自动回退到 CPU。

worker 采用 spawn 进程，各自绑定一个设备、常驻一份模型并维护当前图像编码。设备探测使用隔离的短生命周期探测进程；协调进程不创建 CUDA 上下文。每个 worker 的设备在加载模型前确定，通过显式 device 参数传入适配器。协调器按空闲 worker 动态派发，每个 worker 一个容量1的收件箱；避免共享队列在进程退出前未报告领取状态时无法确认任务归属。不把图片静态切成每卡固定份额。所有框以整张图为一个任务，复用该图编码。

W 个 worker 依次分配给 D 个设备，worker i 绑定 devices[i % D]，各设备 worker 数差不超过1。W<D 时只有前 W 个设备被使用，启动计划明确列出闲置设备；W>D 允许同设备多个模型副本。默认每卡1个，不承诺增加同卡进程会提速；MPS 多进程需真实设备验证。CPU worker 按可用 CPU 数量分配线程预算，限制 PyTorch/BLAS/OpenCV 的嵌套并行，避免进程数乘线程数失控。

协调进程是唯一项目写入者：获得跨进程项目写锁 → 读取标注快照 → 派发纯计算任务 → 验证 image/instance/revision/外部指纹 → 事务保存 → 记账。worker 不构造具有写入副作用的 Project，也不直接改 txt、内部标注或统计索引。项目锁同时约束独立 UI 后端和 CLI；不能只靠进程内 RLock。同一项目第二个独立写入者直接报冲突。

启动前冻结模型配置、权重stat指纹（mtime_ns与大小）、设备计划和图像范围；所有 worker READY 后才派发图片。每个 worker 同时最多持有1张图，总在途最多W张，每个收件箱最多1张，低于原定2W张等待上限，结果队列最多W张，协调进程交错派发/收集/保存，不能先塞满全部任务再收结果。主进程独占结果提交；工作线程只能返回 CPU/RLE 数据，不跨进程传 CUDA tensor。每张图最多一个在途任务，只有保存成功才增加成功数。

缺失模型、设备无效或模型加载 OOM 属于启动失败，不生成“全数据集逐图失败”噪声。单图错误记入报告后继续；worker 崩溃时回收其未完成任务，最多重新派发1次，记录尝试次数，禁止无限重试。所有 worker 不可用则停止。首次 Ctrl+C 停止派发并收尾；再次 Ctrl+C 强制终止，未提交结果不计成功，重跑按既有 mask 跳过已完成工作。退出码：0成功，1有图片失败，2配置/启动失败，130用户中断。

.annodesk/segment-report.json 记录模型/权重标识、选中设备、worker 分配、逐图结果及耗时；不把某个 worker 的存活状态作为恢复依据。页面任务保存相同的执行计划与结果口径，设备/并发参数是每个 job 的快照，运行中修改模型配置不影响在途任务。

### 10.2 Loguru 日志与页面 Logs 抽屉（0.2.0）

增加基础依赖 loguru，统一应用业务日志及标准 logging/Uvicorn 错误。serve、api、ui、segment 每次进程启动建立独立日志会话；--help、docs、doctor、models list 不因查询而创建日志文件。默认位置严格为 ~/.cache/annodesk/{datetime}.log，不采用 macOS 的 ~/Library/Caches 替代路径。datetime 使用本地带微秒的安全文件名，如 2026-10-22_114203_123456.log，排他创建避免多个实例撞名。相对日志目录以命令启动目录解析。

新增运行时 --log-dir 和 --log-level，默认目录如上、文件/终端级别 INFO；DEBUG/TRACE 必须显式启用。正常运行不得重复初始化 sink。默认20MiB轮转、保留14天；启动时也清理过期的本软件日志文件，不动模型及其他缓存。文件以 UTF-8 无 ANSI 输出，格式：

```text
2026-10-22 11:42:03.127 +08:00 | INFO     | Model ready: sam2.1-small; device=cuda:0; workers=3
```

默认前缀不包含源码文件名、函数名和行号。错误堆栈写文件，禁用异常局部变量展开（diagnose=False）；页面只接收经过整理的错误摘要和业务上下文，不显示 Python traceback。图片相对路径属于业务信息，可以显示。禁止记录 token、完整环境变量或未经筛选的凭据配置。文件不可写时只发出一次明确警告，回退终端与内存事件，不因日志目录问题丢失标注。

多进程下由协调进程独占 Loguru 文件 sink。worker 的 READY/启动失败/单图结果通过有界结果通道传回，主进程生成结构化业务事件，统一分配会话内递增 sequence 和接收时间。worker 本轮不产生逐框诊断流，因此不额外建设第二套日志队列；将来需要高频诊断时再增加独立有界队列，不能阻塞或丢弃错误结果。结果通道容量W，日志环形缓冲2000条。日志 sink 内不再次调用 logger；正常退出停止 worker 后关闭 sink；文件不可写不影响保存。

日志分为业务重要事件和诊断事件，是否进入 UI 由结构化 ui_visible 标记决定，不只按等级猜测。页面默认展示：

- 配置/模型解析摘要、模型加载成功/失败及有效模型 ID。
- 设备类型、可见/选中设备、worker 分配及 READY 汇总；大型 worker 池不逐 worker 刷屏。
- 项目打开/锁冲突、批任务开始、取消、恢复、完成及整体成功/失败摘要。
- 保存/推理/设备/导出错误及可操作的原因。

正常 HTTP GET、统计/任务轮询、每次 autosave、逐图成功和每个框的推理细节不进入页面。逐图诊断为 DEBUG；HTTP 正常访问降为 DEBUG，日志读取/stream 端点不产生访问日志，防止自我放大。主任务成功完成用 SUCCESS；可恢复问题 WARNING；单图失败 ERROR；服务/执行器不可继续用 CRITICAL。

页面同类错误按 project/job/event_type/error_code 聚合：首次立即展示，10秒窗口结束再发送一条带新 sequence 的合并摘要，含额外重复次数及最后一个图片示例，不修改已发送事件；摘要的 repeat_count 不重复计算首条。文件和逐图报告仍保留每次原始失败记录。聚合是展示层行为，不能改变失败计数。批处理进度由任务组件展示，不每张图片生成一条页面日志。

Logs 入口常驻，未打开项目也可查看服务启动/模型配置错误。抽屉默认宽640px，可拖动，窄屏最大占满窗口；日志区使用等宽数字和自然换行，内容为“时间 | LEVEL | 详情”，没有 logger 源码来源列。默认 scope 为当前项目（进入页面时尚无项目则为 Service），项目筛选包含全局服务事件，可切换 Service / Current project。

筛选由一个等级下拉框和 = / ≥ 切换组成，默认 ≥ INFO。页面等级提供 INFO(20)、SUCCESS(25)、WARNING(30)、ERROR(40)、CRITICAL(50)。= ERROR 只显示 ERROR，≥ ERROR 包含 ERROR 和 CRITICAL；使用数值严重度比较，不按字符串排序。切换条件重新查询近期匹配记录，不只是过滤当前屏幕。DEBUG/TRACE 诊断留在文件，本轮不加入页面等级菜单。

提供 Pause live / Resume、自动滚动开关、Clear view 和下载当前日志。暂停关闭 stream 并保留游标，后台任务与写盘继续；恢复时按游标补取可用记录，超过保留窗口明确提示 gap，不在浏览器无限积压。Clear view 只重置该页面的显示起点，不删除日志文件。复用数据表/列表虚拟化，最多缓存1000条事件、挂载约60行，长文本折行，单条页面 message 最多2000字符并标明截断，完整信息留在文件，保持滚动位置。提供复制当前视图。每行正文可悬停查看完整UI摘要。抽屉关闭时断开该页面的日志 stream，不改变记录行为。

GET /api/v1/logs 返回最近最多200条匹配记录（limit 上限500）、session_id、next_cursor、gap；GET /api/v1/logs/stream 通过 SSE 发送后续事件。两者支持 scope/project_id、level、comparison=eq|gte。过滤后的 next_cursor 为已扫描的最新序号，不能因无匹配事件停滞。记录结构至少包含 session_id、sequence、timestamp、level_name、level_no、message、event_type、project_id、job_id、worker_id、device、repeat_count。

服务内存仅保留最近2000条 UI 重要事件；游标以(session_id, sequence)唯一。SSE 断线续传和切换筛选不重复追加，15秒心跳，服务重启或超出缓冲区时发出 reset/gap，页面明确提示“部分实时日志已过期”，不伪装完整历史。首次 tail 查询快照与 stream 游标连贯，切项目或切筛选时丢弃旧连接响应。

下载接口仅允许当前日志会话的文件，不接受任意文件路径。当前阶段页面展示本服务会话及其 worker 日志，不自动聚合另一个独立 CLI 的实时日志；独立 segment 的日志在其会话文件中查阅。历史会话浏览可后续扩展。远端部署时文件路径位于后端电脑，浏览器通过 HTTP 获取结构化事件和下载文件，不读取客户端 ~/.cache。

### 10.3 常驻项目统计与批处理进度（0.2.0）

现状：0.1.0 只有 Batch 抽屉中的任务完成数，没有常驻项目审核汇总，且旧 completed 含跳过和失败。本次分离“人工审核状态”“模型任务执行进度”，自动分割成功不能变成 Reviewed 或 Approved。

在顶部主工具栏与三栏工作区之间增加一条紧凑统计栏，横跨工作区，不挤占 Class palette；显示当前任务名、首次复核进度和四个状态计数。与右侧 detection/segmentation 切换同步；默认统计整个项目，不随图片列表搜索/滚动变化。窄屏可换两行，所有计数仍可见。

示例：

```text
Segmentation · Reviewed 80/100 · Not reviewed 20 · Approved 65 · Needs review 10 · Excluded 5
```

Reviewed 在这里表示“已有一次处理决定”，不是“全部审核通过”：numerator = Approved + Needs review + Excluded，denominator = 当前项目总图片数；tooltip 明确公式，Approved 数独立展示。若只有自动分割完成但无人确认，仍是 Not reviewed，不增加人工复核分子。两类任务各自统计，Excluded 为全图共享。空项目显示 No images，不显示 NaN 或0/0百分比。

四项使用排他展示分类：先判断 excluded=True，属于 Excluded；否则按当前任务的 pending/ok/uncertain 分配至前三项。因而四项相加严格等于 total。只改变统计归类，不覆盖底层原审核状态；取消 Excluded 后恢复到之前的审核分类。无内部标注记录的图片默认为 Not reviewed，只有 YOLO 标签或 mask 也不能视为已复核。四项不是任意多选 tag 的累计计数，普通 tags 不参与该进度。

显示的是已提交状态，不把尚未保存的编辑计入服务端统计；保存成功后立即刷新，失败则保留原计数并显示现有保存错误。自动推理使已通过状态回到 pending 时同步扣减。移入项目回收站的图片不再计入总数，恢复后重新计入。Excluded 未移入回收站时仍计入总数。

GET /api/v1/project/statistics?task=detection|segmentation 返回 total、counts{pending,ok,uncertain,excluded}、reviewed、statistics_revision、status=indexing|ready。统计结果来自可重建的项目级 SQLite 元数据索引，只缓存图片 ID、两个任务状态、excluded、标注 revision 和文件变更信息，不存 mask。它不是标注真值来源：启动异步核对/重建，缺失/陈旧时从内部记录恢复；统计错误不使已提交标注回滚。首次扫描完成前显示 Loading statistics，而不是给出伪造的0或部分总数。只读取复核元数据、不解码 mask、不加载原图，也不通过 Project.annotation() 为统计批量创建标注文件。

唯一写入协调进程在事务提交后更新索引和内存汇总，缓存无法更新时标记索引过期并后台重建。恢复日志、重排、导入、排除、回收站操作也走相同失效流程。统计接口不每次全量扫描，支持大数据集。前端保存成功后主动拉取；后台 job 运行时每2秒刷新，浏览器隐藏时暂停，回到前台立即同步。无后台 job 时每10秒检查更新；并发响应按项目/task与请求generation丢弃过期数据；statistics_revision仅为当前索引生命周期内的更新计数，不能跨后端重启比较大小拒收最新请求。

Tasks 抽屉和工具栏中的轻量活动任务入口使用独立口径：启动快照含 input_total 张图片，预检查跳过 S 张，需要处理范围 T=input_total-S 张（含预检查失败）。显示“Batch: F/T finished · A succeeded · B failed · S skipped”，其中 F=A+B。运行中 worker 仅完成计算但主进程尚未保存的结果仍算在途，不算成功。当前进度条为 F/T，不把跳过当作模型推理成功；T=0 显示 No images require segmentation。取消/中断的剩余量单列，任务错误不能让进度显示“全部成功”。

例如项目共100张，25张已有mask/不符合任务条件；需要处理75张，58张成功、2张失败时显示“60/75 finished · 58 succeeded · 2 failed · 25 skipped”，仍有15张待处理。机器进度与上方 Reviewed 计数互不替代。预检查遇到损坏输入要记为可见失败，并纳入 T、B 和 F，不再派给 worker，不能静默归入 skipped；报告给出具体原因。恢复同一 job 保留原任务快照和计数，重新运行新 job 则重新计算待处理集。

#### 任务窗口与进度呈现（0.3更新）

批量处理是低频功能，不常驻大块进度区域、不挤占画布。工具栏始终有 Tasks；空闲只显示按钮。0.3起启动批处理或导出后自动打开居中非模态Tasks窗口，约900px，最大90vw/80vh，可调整大小。关闭/收起仅影响显示，不停止任务；运行时顶部保留 `Tasks ◌ F/T` 和细进度线，随时可再次展开。任务结束保持抽屉开合状态，短暂通知结果；失败保留错误标记，不抢焦点。历史任务折叠，当前任务默认展开。

抽屉利用完整空间分组展示：任务类型/状态/开始时间/已耗时；完整8px条形进度与成功/失败/跳过/剩余数量；只读模型/设备计划；worker编号、设备、当前图片、单图耗时及加载/空闲/停止状态；失败图片和错误；导出后端路径；取消、恢复待处理图片及View logs。

扫描、设备探测、加载模型和最终导出元数据阶段使用不定进度动画和具体阶段文字。处理阶段显示可确定的真实进度，不根据时间编造百分比。单图耗时持续变化，可判断任务仍在执行；不伪造剩余时间预测。导出目前是目录副本，没有压缩归档阶段，进度按已检查图片数推进，最后显示Writing export metadata。取消导出删除本次未完成目录，已有成功导出不动。

日志抽屉记录模型/设备/worker和任务阶段事件；批处理组件展示精确运行进度；统计栏展示项目审核状态。三者共享 project_id/job_id 等标识但不从日志文本推算数量。

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

annodesk segment --project /data/dataset --models-config ./models.json --model <id> 同步处理已有 YOLO 框，不启动 UI 或 HTTP 服务。默认模型来自 JSON，跳过已有 mask、锁定对象及 Excluded 图片；逐图保存到 labels_seg 与内部 RLE，保留 detection 框及类别 ID。中断后再次运行跳过已成功结果；失败明细写入 .annodesk/segment-report.json，单图失败退出码为1，配置/启动失败为2，取消/中断为130，成功为0。输出待人工复核，不自动标为 Approved。

## 13. 验收和分模块实施

以可运行模块依次提交：工程/CLI；领域和YOLO存储；API和保存；Vue工作台；推理适配/任务；类别迁移/清理/导出；集成和发布验证。未完成能力必须在 UI 显式不可用或在 README 说明，禁止用模拟推理假装真实模型。

关键验收覆盖：YOLO多级路径和冲突、缺少YAML、类ID稳定与迁移、box/mask-only语义、切图保存失败与过时推理、无损mask往返、Excluded恢复、不同origin图片/保存/任务、wheel静态资源及tyro入口、缩略图预算、画布坐标/缩放、快捷键焦点/IME。提交前运行ruff和相应测试，前端提交还需类型检查/构建。

新增验收：设备逻辑编号/CUDA_VISIBLE_DEVICES 映射及各种 W/D 组合；spawn worker 崩溃/重派/取消/主进程单写；日志目录和轮转/保留/权限失败；worker 日志不重复写盘、不出现凭据/诊断变量；等级 = 与 ≥（含 SUCCESS/CRITICAL）精确语义；重复错误聚合不影响真实失败计数；SSE 断线/重启/缓冲过期/过滤切换；浏览器事件/DOM 上限；两任务四项排他计数和 Excluded 取消恢复；自动 mask 不变 Approved；统计重建/事务失败/回收站/空项目；batch succeeded/failed/skipped/cancelled 分离。并行单元测试用可控假适配器验证协议，CUDA/MPS 须另做实际设备测试，不能用 mock 结果声称实际性能。

## 14. 设计自检记录

- 已消除多份草案的名称/CLI差异，采用AnnoDesk、tyro、light/English。
- 已区分类别管理与标注赋类、自由tag与固定状态、框标注与框提示、工作labels_seg与训练labels。
- 已区分uv依赖、Node构建、权重准备，避免承诺所有模型自动安装或GPU驱动自动配置。
- 已定义多文件恢复、外部修改、未标注/背景和同stem冲突，不以YOLO txt充当全部编辑数据。
- Python基准遵循用户现有3.13配置；真实推理兼容性必须实测，基础标注不依赖GPU安装成功。

### 交互细化：赋类、提示和品牌图标

Class palette 为日常赋类入口；顶部 Classes 为名称、颜色、ID 管理入口。选中框或 mask 后可直接点左侧类别，或按 C 打开带搜索的类别选择器，以 ↑↓ 选择、Enter 确认、Esc 取消。画布选择模式下双击实例也可打开；右侧提供 Change class 按钮。赋类沿用自动保存/撤销，不修改几何，锁定实例不可赋类。1/2/3 仍用于图片审核状态，不与类别快捷键混用。

全局提示约 150ms 后显示，适用于 pointer hover 及键盘 focus，替代浏览器无法控制延迟的 title 提示。提示展示作用及已有快捷键，离开、点击、滚动、Esc 时关闭；窗口边缘自动调整位置。图标采用同一份 SVG：蓝色标注框与白色 mask 轮廓，复用为 favicon 与左上角品牌标识。

Tags 抽屉顶部始终展示四个内置审核状态及固定颜色/含义（Not reviewed、Approved、Needs review、Excluded），标注 Read only，不提供改名、改色或删除控件。下方独立 Custom image tags 分组管理自定义标签；内置项不写入可编辑 tags 字典。审核前三项按任务记录，Excluded 仍为整图标记，二者语义不变。

快捷键补充：X 或 Delete 删除当前选中标注；←/→ 与 A/D 均可前后切图。沿用输入框、IME、弹层与锁定实例的快捷键保护，帮助抽屉、删除按钮提示与状态栏保持同步。

快捷键文案约定：同一功能的替代操作使用 or（例如 X or Delete、C or double-click），不同功能依次对应的按键使用 /（例如 Previous / next image 对应 A / D or ← / →）。撤销与重做分行展示，避免组合键歧义。

面向安装包用户的操作说明保存于 docs/user-guide.md，与开发者 README 分离。该指南作为 package long description 并以 annodesk/docs/user-guide.md 资源随 wheel 发布，sdist 同时包含源文档；annodesk docs 输出当前安装版本指南，--output 导出 Markdown 且拒绝覆盖已有文件。

入口 HTML（含 /index.html）与状态 JSON 使用 Cache-Control: no-store；HTML 不使用旧 ETag/Last-Modified 条件请求返回 304，以免升级后仍引用已移除的 hash 静态资源。客户端配置和 API fetch 同样显式 no-store。未打开项目时仍由前端空状态分支停止拉取图片列表，不将 409 改为空数据掩盖错误。

### 1.2 增补自检与参考

- 区分了模型 ID、模型目录和执行设备；禁止把 --devices 再当物理编号解析。
- 多进程共享计算不共享文件写入，统计索引是可重建派生数据，不作为标签真值。
- UI 日志只显示重要业务事件；文件保留错误细节；等级条件明确 = 与 ≥，无正常轮询刷屏。
- 通过 Excluded 优先分类保证四项之和等于 total；区分首次复核、Approved 和机器推理完成。
- 明确当前会话日志范围、跨电脑日志位置、SSE 缓冲上限和计数持久化边界；基础和实际 spawn 协议测试与真实加速器测试分开，未用模拟掩盖真实推理验证限制。

实现参考：[Loguru logger API](https://loguru.readthedocs.io/en/stable/api/logger.html)、[PyTorch multiprocessing best practices](https://docs.pytorch.org/docs/2.14/notes/multiprocessing.html)、[NVIDIA CUDA_VISIBLE_DEVICES](https://docs.nvidia.com/deploy/topics/topic_5_2_1.html)。

0.2.0实施约束：任务仍以JSON持久化，导出仍为目录副本；不引入分布式任务系统、历史日志数据库或GPU性能自动调参。旧0.1任务记录可查看，但计数口径不同，不直接恢复；重新运行新批次会跳过已有结果。统计数据库可删除重建，不删除内部标注。

预检仅按时间节流写任务检查点，阶段结束/取消/异常强制保存；每张推理结果保存后的记账继续持久化，避免预检阶段对完整remaining产生二次方无效磁盘写入。worker与设备探测子进程忽略SIGINT，由协调者控制取消与强制终止。损坏的派生SQLite自动重建，权威标注保持不动。日志断线使用最新游标受控重连，Clear view后旧事件不应重新出现。

模型选择器的悬停提示只呈现简短状态与操作建议，不绑定后端原始error字符串，不展示服务端绝对路径或目录搜索过程。完整模型解析错误继续由CLI诊断和实际运行错误日志提供。

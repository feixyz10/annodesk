# AnnoDesk 0.3：自动框、严格类别校验与模型/任务窗口

状态：2026-10-22 已实现并通过自动化与合成数据交互验证，真实模型/加速器验证边界见§7。与主 spec 冲突时，本增补中涉及0.3功能的条款优先。保持浅色界面（0.4起支持英文/简体中文）、本地模型、tyro与单协调者写入；不引入通用插件框架或分布式服务。

## 1. 常驻统计与两类窗口

审核统计栏始终位于工具栏下，按 Detection/Segmentation 显示全项目 Reviewed 与四类排他计数，不随Tasks关闭或任务结束隐藏。Reviewed=Approved+Needs review+Excluded。自动结果不算人工审核。

模型设置改为居中模态窗口（约900px，最大90vw/80vh）：Detection/Segmentation、模型选择与Available/Loaded状态、显式Load、兼容检查、检测阈值/conf、NMS IoU、imgsz、max_det、模型类别筛选、设备设置及允许新增类别。Apply才保存参数；Cancel不应用未确认设置。加载是运行时动作，可独立于Apply；提示中不包含后端路径，主动展开的诊断与日志可包含。

工作台仅保留当前任务模型的紧凑设置入口、Detect current/Segment current及自动切图处理开关；框来自mask的操作放在当前图片/选中实例区域。Pan与缩放/Fit保持同组。

Tasks改为居中非模态任务窗（约900px，最大90vw/80vh），不遮罩或锁住整个工作台。启动自动展开，关闭仅收起，顶部继续显示轻量进度；完成不抢焦点。展示配置快照、时间、进度、实例计数、worker、错误及历史任务。窗口内键盘操作不能误触画布快捷键，点击画布后仍可标注。Logs/Classes/Tags保留右侧抽屉。

## 2. 检测模型与类别来源

models.json的模型条目增加task=detection|segmentation、backend=ultralytics，以及可选classes_file；旧SAM条目自动属于segmentation。default_model继续指SAM，新增可选default_detection_model。仅有det条目的配置也合法，但不得把det模型用于SAM提示。

source依然精确到模型目录，目录内必须有唯一兼容.pt，禁止下载。classes_file支持JSON/YAML，使用names数组或ID到名称的字典，非空、名称非空且唯一、ID为连续0..nc-1；相对models.json解析，不尝试HF_MODELS。

优先读取标准Ultralytics检测权重的可靠names。缺少/仅占位名称时要求classes_file并验证模型nc。若两处都有可靠定义，完整(ID,name)表必须相同，否则直接报错；不得通过sidecar偷偷改写真实模型类别。仅含state_dict、无法初始化检测模型的文件，不因有类别文件就承诺兼容。

严格项目兼容：模型和项目的(ID,name)集合完全相同，或任一为另一的子集。相同ID不同名、同名不同ID、互不包含都报错，不做别名/大小写转换/重映射。类别文件变化、模型变化、项目类别重排/改名后重新检查。项目内部仍以UUID关联实例，数字ID用于对外序列化。

## 3. 新类别与提交一致性

Allow new classes from this model默认关闭，按项目/模型保存，任务启动后冻结。关闭时丢弃超出项目的类别并统计；开启时只有通过conf/NMS/类别筛选/几何校验且最终保存成功的检测结果才引入类别。保持模型数字ID，新建项目UUID和颜色，不按max+1重新编号。

类别元数据、data.yaml、内部实例和YOLO投影在同一恢复日志事务中提交；revision/外部指纹冲突不得留下幽灵类别。失败图片不新增类别。所有worker只返回候选，主协调者验证当前类别体系并提交。已删除类别的保留记录不得被自动恢复。兼容空项目但toggle关闭时无可接收类别，开始前明确报错。

允许工作类别ID空洞；重新打开不能补出未识别类别。训练导出生成连续ID副本和class-id-map.json，不回写工作ID；不能承诺稀疏data.yaml可直接用于Ultralytics训练。所有新增类别在Class palette可用，可手动调色。

## 4. 操作语义

Detect current及Auto-detect on navigation（默认关）：由检测模型产生可编辑的框、类别与原始置信度/模型来源。默认fill_empty，只处理尚无实例的图片；append显式追加，按相同目标类别、IoU>=0.7去重（mask实例可用其临时包围框检查）。不替换人工实例，不修改已有mask，不自动确认空背景。没有结果是成功处理0个框，审核状态不变。发生新增时Detection回到pending。

Boxes from masks：选中实例、当前图、批量都可用。纯几何计算，不加载Torch/SAM或GPU；RLE优先，polygon后备；RLE按像素边界[xmin,ymin,xmax+1,ymax+1]，polygon按连续坐标范围；裁剪到图片范围，空/退化几何跳过，不连通部分仍为同一实例的一个包围框。保留实例UUID/类别/mask；默认仅缺框，Recalculate boxes显式允许替换未锁定框。框后续可人工调整，不随mask编辑自动重算。只增加/改框不修改Segmentation状态；Detection有变化时回到pending。普通SAM仍不自动保存框。

## 5. 范围、审核筛选与预检

批任务类型：detection、segmentation、boxes_from_masks，导出保持独立。默认只选pending，可显式选择uncertain/ok；Excluded始终跳过。det及mask转box按Detection审核筛选，SAM按Segmentation筛选。锁定按实例保护；状态筛选不授权覆盖人工标注。

范围支持全项目或当前图片搜索过滤结果。预览只读、不物化内部标注：固定优先级excluded→review_state→无可处理内容→eligible，损坏输入独立计失败；给出input_total、各跳过数、需处理数及类别兼容摘要。开始重新验证并冻结范围、参数、类别表、模型/类别文件/设备计划。单独的scope预览不冒充已完成模型加载/类别验证。

Resume延续原任务范围/配置，不受当前筛选和参数影响；checkpoint或类别表变化不能静默恢复。新批次重新计算。检测任务运行期间禁止手动新增、改名和重排类别（颜色可调整）；恢复校验项目类别快照，允许本任务此前成功保存所引入的类别。排队期间变为不符合审核筛选的图片拒绝处理并计入失败，保留人工决定。F/T图片进度与boxes_added/dropped等实例计数分开；成功必须在协调者保存后计数。取消、保存冲突、worker崩溃、项目写锁沿用0.2约定。

## 6. API与CLI

保留现有segment接口和SegmentRequest兼容，增加operation与检测/类别/审核/范围参数；当前图提供detect、boxes-from-masks端点，/jobs/preview只预览范围，/jobs支持三类任务。/models/check进行独立CPU探测与兼容检查；/models/load在交互执行器加载指定设备模型；/model-settings保存项目级模型参数，不写标注。

CLI增加detect、boxes-from-masks；segment增加审核筛选。三类CLI不需要UI/HTTP，日志、退出码、报告、恢复与设备语义一致；几何任务不接受GPU/多worker配置。检测报告包含类别快照、参数、逐图结果、新增框与丢弃数量；内部存储原始置信度，不扩展YOLO标准txt列。

## 7. 验证与边界

验证旧配置兼容、det-only配置、sidecar路径/冲突/nc、严格包含关系、空项目与toggle、稀疏ID重开/导出、同事务冲突保护、类别变化拒绝在途保存、mask单像素/孔洞/断连/polygon、锁定与审核失效、只读预检、范围/恢复、spawn检测候选单写、异步返回保留编辑。前端验证窗口可收起且不停止任务、设置Apply/Cancel、状态区分与常驻统计。使用临时数据/假适配器验证协议，真实权重和CUDA/MPS仍需目标机器实测。

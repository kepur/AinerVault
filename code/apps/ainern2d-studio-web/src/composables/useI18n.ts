/**
 * useI18n composable
 * Usage in any page component:
 *   const { t, locale } = useI18n()
 *   then use t('key') in template
 */
import { computed } from 'vue'
import { useLocaleStore } from '@/stores/locale'

// ─── Full Translation Map ──────────────────────────────────────────────────────
const translations: Record<string, Record<string, string>> = {
    // ── Common ─────────────────────────────────────────────────────────────────
    'common.save': { 'zh-CN': '保存', 'en-US': 'Save', 'ja-JP': '保存', 'es-ES': 'Guardar', 'ar-SA': 'حفظ' },
    'common.cancel': { 'zh-CN': '取消', 'en-US': 'Cancel', 'ja-JP': 'キャンセル', 'es-ES': 'Cancelar', 'ar-SA': 'إلغاء' },
    'common.delete': { 'zh-CN': '删除', 'en-US': 'Delete', 'ja-JP': '削除', 'es-ES': 'Eliminar', 'ar-SA': 'حذف' },
    'common.edit': { 'zh-CN': '编辑', 'en-US': 'Edit', 'ja-JP': '編集', 'es-ES': 'Editar', 'ar-SA': 'تعديل' },
    'common.create': { 'zh-CN': '创建', 'en-US': 'Create', 'ja-JP': '作成', 'es-ES': 'Crear', 'ar-SA': 'إنشاء' },
    'common.search': { 'zh-CN': '搜索', 'en-US': 'Search', 'ja-JP': '検索', 'es-ES': 'Buscar', 'ar-SA': 'بحث' },
    'common.loading': { 'zh-CN': '加载中…', 'en-US': 'Loading…', 'ja-JP': '読込中…', 'es-ES': 'Cargando…', 'ar-SA': 'جارٍ التحميل…' },
    'common.confirm': { 'zh-CN': '确认', 'en-US': 'Confirm', 'ja-JP': '確認', 'es-ES': 'Confirmar', 'ar-SA': 'تأكيد' },
    'common.submit': { 'zh-CN': '提交', 'en-US': 'Submit', 'ja-JP': '送信', 'es-ES': 'Enviar', 'ar-SA': 'إرسال' },
    'common.refresh': { 'zh-CN': '刷新', 'en-US': 'Refresh', 'ja-JP': '更新', 'es-ES': 'Actualizar', 'ar-SA': 'تحديث' },
    'common.back': { 'zh-CN': '返回', 'en-US': 'Back', 'ja-JP': '戻る', 'es-ES': 'Volver', 'ar-SA': 'رجوع' },
    'common.status': { 'zh-CN': '状态', 'en-US': 'Status', 'ja-JP': 'ステータス', 'es-ES': 'Estado', 'ar-SA': 'الحالة' },
    'common.name': { 'zh-CN': '名称', 'en-US': 'Name', 'ja-JP': '名前', 'es-ES': 'Nombre', 'ar-SA': 'الاسم' },
    'common.actions': { 'zh-CN': '操作', 'en-US': 'Actions', 'ja-JP': '操作', 'es-ES': 'Acciones', 'ar-SA': 'الإجراءات' },
    'common.noData': { 'zh-CN': '暂无数据', 'en-US': 'No data', 'ja-JP': 'データなし', 'es-ES': 'Sin datos', 'ar-SA': 'لا توجد بيانات' },
    'common.total': { 'zh-CN': '共', 'en-US': 'Total', 'ja-JP': '合計', 'es-ES': 'Total', 'ar-SA': 'الإجمالي' },
    'common.type': { 'zh-CN': '类型', 'en-US': 'Type', 'ja-JP': 'タイプ', 'es-ES': 'Tipo', 'ar-SA': 'النوع' },
    'common.createdAt': { 'zh-CN': '创建时间', 'en-US': 'Created At', 'ja-JP': '作成日時', 'es-ES': 'Creado en', 'ar-SA': 'تاريخ الإنشاء' },
    'common.updatedAt': { 'zh-CN': '更新时间', 'en-US': 'Updated At', 'ja-JP': '更新日時', 'es-ES': 'Actualizado en', 'ar-SA': 'تاريخ التحديث' },
    'common.success': { 'zh-CN': '成功', 'en-US': 'Success', 'ja-JP': '成功', 'es-ES': 'Éxito', 'ar-SA': 'نجاح' },
    'common.failed': { 'zh-CN': '失败', 'en-US': 'Failed', 'ja-JP': '失敗', 'es-ES': 'Error', 'ar-SA': 'فشل' },
    'common.queued': { 'zh-CN': '排队中', 'en-US': 'Queued', 'ja-JP': 'キュー', 'es-ES': 'En cola', 'ar-SA': 'في الانتظار' },
    'common.running': { 'zh-CN': '运行中', 'en-US': 'Running', 'ja-JP': '実行中', 'es-ES': 'Ejecutando', 'ar-SA': 'جارٍ التشغيل' },
    'common.details': { 'zh-CN': '详情', 'en-US': 'Details', 'ja-JP': '詳細', 'es-ES': 'Detalles', 'ar-SA': 'تفاصيل' },
    'common.description': { 'zh-CN': '描述', 'en-US': 'Description', 'ja-JP': '説明', 'es-ES': 'Descripción', 'ar-SA': 'الوصف' },
    'common.enabled': { 'zh-CN': '已启用', 'en-US': 'Enabled', 'ja-JP': '有効', 'es-ES': 'Habilitado', 'ar-SA': 'مُفعَّل' },
    'common.disabled': { 'zh-CN': '已禁用', 'en-US': 'Disabled', 'ja-JP': '無効', 'es-ES': 'Deshabilitado', 'ar-SA': 'معطَّل' },
    'common.init': { 'zh-CN': '一键初始化', 'en-US': 'One-Click Init', 'ja-JP': 'ワンクリック初期化', 'es-ES': 'Inicializar', 'ar-SA': 'تهيئة بنقرة واحدة' },

    // ── Dashboard ───────────────────────────────────────────────────────────────
    'dashboard.title': { 'zh-CN': '系统概览', 'en-US': 'System Overview', 'ja-JP': 'システム概要', 'es-ES': 'Resumen del Sistema', 'ar-SA': 'نظرة عامة على النظام' },
    'dashboard.providers': { 'zh-CN': 'Provider 数量', 'en-US': 'Providers', 'ja-JP': 'プロバイダ数', 'es-ES': 'Proveedores', 'ar-SA': 'مزودو الخدمة' },
    'dashboard.models': { 'zh-CN': '模型 Profile 数量', 'en-US': 'Model Profiles', 'ja-JP': 'モデルプロファイル数', 'es-ES': 'Perfiles de Modelos', 'ar-SA': 'ملفات تعريف النماذج' },
    'dashboard.novels': { 'zh-CN': '小说数量', 'en-US': 'Novels', 'ja-JP': '小説数', 'es-ES': 'Novelas', 'ar-SA': 'الروايات' },
    'dashboard.runs': { 'zh-CN': '运行任务数', 'en-US': 'Run Tasks', 'ja-JP': '実行タスク数', 'es-ES': 'Tareas Ejecutadas', 'ar-SA': 'مهام التشغيل' },
    'dashboard.quickEntry': { 'zh-CN': '快捷入口', 'en-US': 'Quick Links', 'ja-JP': 'クイックリンク', 'es-ES': 'Accesos Rápidos', 'ar-SA': 'روابط سريعة' },
    'dashboard.sysInit': { 'zh-CN': '系统初始化', 'en-US': 'System Initialization', 'ja-JP': 'システム初期化', 'es-ES': 'Inicialización del Sistema', 'ar-SA': 'تهيئة النظام' },
    'dashboard.initBasic': { 'zh-CN': '一键初始化基础数据', 'en-US': 'Init Basic Data', 'ja-JP': '基本データ初期化', 'es-ES': 'Inicializar Datos Básicos', 'ar-SA': 'تهيئة البيانات الأساسية' },
    'dashboard.initAll': { 'zh-CN': '🚀 全局一键初始化', 'en-US': '🚀 Full Init', 'ja-JP': '🚀 全体初期化', 'es-ES': '🚀 Inicialización Completa', 'ar-SA': '🚀 تهيئة كاملة' },
    'dashboard.go.novels': { 'zh-CN': '📖 小说管理', 'en-US': '📖 Novels', 'ja-JP': '📖 小説管理', 'es-ES': '📖 Novelas', 'ar-SA': '📖 إدارة الروايات' },
    'dashboard.go.providers': { 'zh-CN': '⚡ Provider 接入', 'en-US': '⚡ Providers', 'ja-JP': '⚡ プロバイダ', 'es-ES': '⚡ Proveedores', 'ar-SA': '⚡ مزودو الخدمة' },
    'dashboard.go.modelCatalog': { 'zh-CN': '📋 模型目录', 'en-US': '📋 Model Catalog', 'ja-JP': '📋 モデルカタログ', 'es-ES': '📋 Catálogo de Modelos', 'ar-SA': '📋 كتالوج النماذج' },
    'dashboard.go.kbAssets': { 'zh-CN': '📚 知识资产中心', 'en-US': '📚 KB Assets', 'ja-JP': '📚 ナレッジセンター', 'es-ES': '📚 Activos KB', 'ar-SA': '📚 مركز الأصول' },
    'dashboard.go.runs': { 'zh-CN': '🚀 Run 运行中心', 'en-US': '🚀 Run Center', 'ja-JP': '🚀 実行センター', 'es-ES': '🚀 Centro de Ejecución', 'ar-SA': '🚀 مركز التشغيل' },
    'dashboard.go.roles': { 'zh-CN': '🎭 角色与 Persona', 'en-US': '🎭 Roles & Personas', 'ja-JP': '🎭 ロールとペルソナ', 'es-ES': '🎭 Roles y Personas', 'ar-SA': '🎭 الأدوار والشخصيات' },

    // ── Novels ──────────────────────────────────────────────────────────────────
    'novels.title': { 'zh-CN': '小说管理', 'en-US': 'Novel Management', 'ja-JP': '小説管理', 'es-ES': 'Gestión de Novelas', 'ar-SA': 'إدارة الروايات' },
    'novels.create': { 'zh-CN': '新建小说', 'en-US': 'New Novel', 'ja-JP': '新規小説', 'es-ES': 'Nueva Novela', 'ar-SA': 'رواية جديدة' },
    'novels.novelTitle': { 'zh-CN': '小说标题', 'en-US': 'Novel Title', 'ja-JP': '小説タイトル', 'es-ES': 'Título de la Novela', 'ar-SA': 'عنوان الرواية' },
    'novels.summary': { 'zh-CN': '简介', 'en-US': 'Summary', 'ja-JP': 'あらすじ', 'es-ES': 'Resumen', 'ar-SA': 'ملخص' },
    'novels.language': { 'zh-CN': '语言', 'en-US': 'Language', 'ja-JP': '言語', 'es-ES': 'Idioma', 'ar-SA': 'اللغة' },
    'novels.chapters': { 'zh-CN': '章节', 'en-US': 'Chapters', 'ja-JP': '章', 'es-ES': 'Capítulos', 'ar-SA': 'الفصول' },
    'novels.viewDetail': { 'zh-CN': '查看详情', 'en-US': 'View Details', 'ja-JP': '詳細を見る', 'es-ES': 'Ver Detalles', 'ar-SA': 'عرض التفاصيل' },
    'novels.noNovels': { 'zh-CN': '尚未创建任何小说', 'en-US': 'No novels yet', 'ja-JP': '小説がまだありません', 'es-ES': 'Aún no hay novelas', 'ar-SA': 'لا توجد روايات بعد' },

    // ── Runs ────────────────────────────────────────────────────────────────────
    'runs.title': { 'zh-CN': 'Run 运行中心', 'en-US': 'Run Center', 'ja-JP': '実行センター', 'es-ES': 'Centro de Ejecución', 'ar-SA': 'مركز التشغيل' },
    'runs.runId': { 'zh-CN': 'Run ID', 'en-US': 'Run ID', 'ja-JP': 'Run ID', 'es-ES': 'ID de Ejecución', 'ar-SA': 'معرف التشغيل' },
    'runs.progress': { 'zh-CN': '进度', 'en-US': 'Progress', 'ja-JP': '進捗', 'es-ES': 'Progreso', 'ar-SA': 'التقدم' },
    'runs.stage': { 'zh-CN': '阶段', 'en-US': 'Stage', 'ja-JP': 'ステージ', 'es-ES': 'Etapa', 'ar-SA': 'المرحلة' },
    'runs.filter': { 'zh-CN': '按状态筛选', 'en-US': 'Filter by Status', 'ja-JP': 'ステータスでフィルタ', 'es-ES': 'Filtrar por Estado', 'ar-SA': 'تصفية حسب الحالة' },
    'runs.viewSnapshot': { 'zh-CN': '查看快照', 'en-US': 'View Snapshot', 'ja-JP': 'スナップショット', 'es-ES': 'Ver Snapshot', 'ar-SA': 'عرض اللقطة' },
    'runs.viewTimeline': { 'zh-CN': '查看时间线', 'en-US': 'View Timeline', 'ja-JP': 'タイムライン', 'es-ES': 'Ver Línea de Tiempo', 'ar-SA': 'عرض الجدول' },

    // ── Assets / KB ─────────────────────────────────────────────────────────────
    'assets.title': { 'zh-CN': '素材库', 'en-US': 'Asset Library', 'ja-JP': 'アセットライブラリ', 'es-ES': 'Biblioteca de Activos', 'ar-SA': 'مكتبة الأصول' },
    'assets.assetId': { 'zh-CN': '素材 ID', 'en-US': 'Asset ID', 'ja-JP': 'アセット ID', 'es-ES': 'ID de Activo', 'ar-SA': 'معرف الأصل' },
    'assets.uri': { 'zh-CN': '资源 URI', 'en-US': 'Resource URI', 'ja-JP': 'リソース URI', 'es-ES': 'URI del recurso', 'ar-SA': 'URI المورد' },
    'assets.filter.all': { 'zh-CN': '全部类型', 'en-US': 'All Types', 'ja-JP': 'すべてのタイプ', 'es-ES': 'Todos los Tipos', 'ar-SA': 'جميع الأنواع' },

    // ── Models & Providers ──────────────────────────────────────────────────────
    'models.title': { 'zh-CN': '模型资产管理', 'en-US': 'Model Asset Management', 'ja-JP': 'モデル資産管理', 'es-ES': 'Gestión de Modelos', 'ar-SA': 'إدارة النماذج' },
    'models.provider': { 'zh-CN': 'Provider', 'en-US': 'Provider', 'ja-JP': 'プロバイダ', 'es-ES': 'Proveedor', 'ar-SA': 'المزود' },
    'models.endpoint': { 'zh-CN': '接入端点', 'en-US': 'Endpoint', 'ja-JP': 'エンドポイント', 'es-ES': 'Punto de Acceso', 'ar-SA': 'نقطة الوصول' },
    'models.addProvider': { 'zh-CN': '添加 Provider', 'en-US': 'Add Provider', 'ja-JP': 'プロバイダを追加', 'es-ES': 'Agregar Proveedor', 'ar-SA': 'إضافة مزود' },
    'models.addProfile': { 'zh-CN': '添加 Model Profile', 'en-US': 'Add Model Profile', 'ja-JP': 'モデルプロファイルを追加', 'es-ES': 'Agregar Perfil de Modelo', 'ar-SA': 'إضافة ملف تعريف نموذج' },
    'models.purpose': { 'zh-CN': '用途', 'en-US': 'Purpose', 'ja-JP': '用途', 'es-ES': 'Propósito', 'ar-SA': 'الغرض' },
    'models.authMode': { 'zh-CN': '认证方式', 'en-US': 'Auth Mode', 'ja-JP': '認証モード', 'es-ES': 'Modo de Auth', 'ar-SA': 'وضع المصادقة' },

    // ── Model Routing ───────────────────────────────────────────────────────────
    'routing.title': { 'zh-CN': 'AI 路由顾问', 'en-US': 'AI Routing Advisor', 'ja-JP': 'AIルーティング顧問', 'es-ES': 'Asesor de Rutas IA', 'ar-SA': 'مستشار توجيه الذكاء الاصطناعي' },
    'routing.autoAdvisor': { 'zh-CN': 'AI 自动路由顾问', 'en-US': 'Auto Router Advisor', 'ja-JP': 'AIオートルーター', 'es-ES': 'Asesor Automático', 'ar-SA': 'مستشار التوجيه التلقائي' },
    'routing.manualRouting': { 'zh-CN': '模型路由策略（手动配置）', 'en-US': 'Manual Routing Strategy', 'ja-JP': '手動ルーティング', 'es-ES': 'Estrategia Manual', 'ar-SA': 'استراتيجية يدوية' },
    'routing.mvpList': { 'zh-CN': '必备模型清单 (MVP)', 'en-US': 'MVP Model List', 'ja-JP': 'MVPモデル一覧', 'es-ES': 'Lista MVP de Modelos', 'ar-SA': 'قائمة النماذج MVP' },
    'routing.runAdvisor': { 'zh-CN': '✦ 请求 AI 诊断与自动路由', 'en-US': '✦ Request AI Diagnosis & Auto-Route', 'ja-JP': '✦ AI診断＆自動ルート実行', 'es-ES': '✦ Solicitar Diagnóstico IA', 'ar-SA': '✦ طلب تشخيص الذكاء الاصطناعي' },
    'routing.advisorDesc': { 'zh-CN': '此功能将自动请求系统中具备文本生成能力的大模型，扫描您当前接入的所有 Provider 及能力，为您一键生成最佳的 Model Profile 集合和路由映射配置。', 'en-US': 'This feature automatically requests LLMs capable of text generation to scan all connected Providers and capabilities, generating the optimal Model Profile set and routing configuration.', 'ja-JP': 'この機能は、テキスト生成可能なLLMに自動でリクエストし、接続されたすべてのプロバイダをスキャンして最適なModel Profileとルーティング設定を生成します。', 'es-ES': 'Esta función solicita automáticamente a los LLM con capacidad de generación de texto que escaneen todos los Proveedores conectados y generen la configuración óptima de Model Profile y enrutamiento.', 'ar-SA': 'تطلب هذه الميزة تلقائياً من النماذج اللغوية الكبيرة القادرة على توليد النصوص فحص جميع المزودين المتصلين وإنشاء أفضل تكوين لـ Model Profile والتوجيه.' },
    'routing.selectProvider': { 'zh-CN': '指定 AI 分析专家（可选）', 'en-US': 'Specify AI Expert (Optional)', 'ja-JP': 'AI専門家を指定（任意）', 'es-ES': 'Especificar Experto IA (Opcional)', 'ar-SA': 'تحديد خبير الذكاء الاصطناعي (اختياري)' },
    'routing.autoSelect': { 'zh-CN': '自动选择适合的 Provider', 'en-US': 'Auto-select Provider', 'ja-JP': 'プロバイダを自動選択', 'es-ES': 'Selección automática de proveedor', 'ar-SA': 'اختيار المزود تلقائياً' },
    'routing.startHint': { 'zh-CN': '点击上方按钮开始诊断您的模型配置', 'en-US': 'Click the button above to start diagnosing your model configuration', 'ja-JP': '上のボタンをクリックしてモデル設定の診断を開始', 'es-ES': 'Haga clic en el botón de arriba para iniciar el diagnóstico', 'ar-SA': 'انقر على الزر أعلاه لبدء تشخيص تكوين النموذج' },

    // ── KB Assets ───────────────────────────────────────────────────────────────
    'kb.title': { 'zh-CN': '知识资产中心', 'en-US': 'KB Asset Center', 'ja-JP': 'ナレッジベースセンター', 'es-ES': 'Centro de Activos KB', 'ar-SA': 'مركز أصول قاعدة المعرفة' },
    'kb.upload': { 'zh-CN': '上传知识文档', 'en-US': 'Upload Knowledge Doc', 'ja-JP': '知識ドキュメントをアップロード', 'es-ES': 'Subir Documento de Conocimiento', 'ar-SA': 'رفع وثيقة المعرفة' },
    'kb.collection': { 'zh-CN': '知识集合', 'en-US': 'Collection', 'ja-JP': 'コレクション', 'es-ES': 'Colección', 'ar-SA': 'مجموعة' },
    'kb.publish': { 'zh-CN': '发布到 RAG', 'en-US': 'Publish to RAG', 'ja-JP': 'RAGに公開', 'es-ES': 'Publicar en RAG', 'ar-SA': 'نشر إلى RAG' },
    'kb.chunks': { 'zh-CN': '分块数', 'en-US': 'Chunks', 'ja-JP': 'チャンク数', 'es-ES': 'Fragmentos', 'ar-SA': 'الأجزاء' },
    'kb.version': { 'zh-CN': '版本', 'en-US': 'Version', 'ja-JP': 'バージョン', 'es-ES': 'Versión', 'ar-SA': 'الإصدار' },

    // ── Auth / Users ─────────────────────────────────────────────────────────────
    'auth.title': { 'zh-CN': '账号与权限管理', 'en-US': 'Accounts & Permissions', 'ja-JP': 'アカウントと権限管理', 'es-ES': 'Cuentas y Permisos', 'ar-SA': 'الحسابات والأذونات' },
    'auth.email': { 'zh-CN': '邮箱', 'en-US': 'Email', 'ja-JP': 'メール', 'es-ES': 'Correo', 'ar-SA': 'البريد الإلكتروني' },
    'auth.displayName': { 'zh-CN': '显示名称', 'en-US': 'Display Name', 'ja-JP': '表示名', 'es-ES': 'Nombre Visible', 'ar-SA': 'الاسم المعروض' },
    'auth.role': { 'zh-CN': '角色', 'en-US': 'Role', 'ja-JP': 'ロール', 'es-ES': 'Rol', 'ar-SA': 'الدور' },
    'auth.createUser': { 'zh-CN': '创建账号', 'en-US': 'Create Account', 'ja-JP': 'アカウント作成', 'es-ES': 'Crear Cuenta', 'ar-SA': 'إنشاء حساب' },
    'auth.password': { 'zh-CN': '初始密码', 'en-US': 'Initial Password', 'ja-JP': '初期パスワード', 'es-ES': 'Contraseña Inicial', 'ar-SA': 'كلمة المرور الأولية' },

    // ── Audit ────────────────────────────────────────────────────────────────────
    'audit.title': { 'zh-CN': '审计日志', 'en-US': 'Audit Logs', 'ja-JP': '監査ログ', 'es-ES': 'Registros de Auditoría', 'ar-SA': 'سجلات التدقيق' },
    'audit.eventType': { 'zh-CN': '事件类型', 'en-US': 'Event Type', 'ja-JP': 'イベントタイプ', 'es-ES': 'Tipo de Evento', 'ar-SA': 'نوع الحدث' },
    'audit.producer': { 'zh-CN': '来源', 'en-US': 'Producer', 'ja-JP': '発信元', 'es-ES': 'Origen', 'ar-SA': 'المصدر' },
    'audit.payload': { 'zh-CN': '载荷', 'en-US': 'Payload', 'ja-JP': 'ペイロード', 'es-ES': 'Carga útil', 'ar-SA': 'الحمل' },

    // ── Culture Pack ─────────────────────────────────────────────────────────────
    'culture.title': { 'zh-CN': '文化包 / 世界观配置', 'en-US': 'Culture Pack / Worldview', 'ja-JP': '文化パック / 世界観設定', 'es-ES': 'Paquete Cultural / Universo', 'ar-SA': 'حزمة الثقافة / العالم' },
    'culture.packId': { 'zh-CN': '包 ID', 'en-US': 'Pack ID', 'ja-JP': 'パック ID', 'es-ES': 'ID de Paquete', 'ar-SA': 'معرف الحزمة' },
    'culture.displayName': { 'zh-CN': '显示名称', 'en-US': 'Display Name', 'ja-JP': '表示名', 'es-ES': 'Nombre Visible', 'ar-SA': 'الاسم المعروض' },

    // ── NLE Timeline ─────────────────────────────────────────────────────────────
    'nle.title': { 'zh-CN': 'NLE 时间线编辑器', 'en-US': 'NLE Timeline Editor', 'ja-JP': 'NLEタイムラインエディタ', 'es-ES': 'Editor de Línea de Tiempo NLE', 'ar-SA': 'محرر الجدول الزمني NLE' },
    'nle.loadRun': { 'zh-CN': '加载 Run', 'en-US': 'Load Run', 'ja-JP': 'Run を読み込む', 'es-ES': 'Cargar Ejecución', 'ar-SA': 'تحميل التشغيل' },
    'nle.save': { 'zh-CN': '💾 保存', 'en-US': '💾 Save', 'ja-JP': '💾 保存', 'es-ES': '💾 Guardar', 'ar-SA': '💾 حفظ' },
    'nle.assetLib': { 'zh-CN': '素材库', 'en-US': 'Asset Library', 'ja-JP': 'アセットライブラリ', 'es-ES': 'Biblioteca de Activos', 'ar-SA': 'مكتبة الأصول' },
    'nle.propPanel': { 'zh-CN': '属性面板', 'en-US': 'Properties', 'ja-JP': 'プロパティ', 'es-ES': 'Propiedades', 'ar-SA': 'الخصائص' },
    'nle.shots': { 'zh-CN': '🎬 分镜（Shots）', 'en-US': '🎬 Shots', 'ja-JP': '🎬 ショット', 'es-ES': '🎬 Tomas', 'ar-SA': '🎬 اللقطات' },
    'nle.dialogues': { 'zh-CN': '🎤 对白（Dialogues）', 'en-US': '🎤 Dialogues', 'ja-JP': '🎤 ダイアログ', 'es-ES': '🎤 Diálogos', 'ar-SA': '🎤 الحوارات' },
    'nle.regen': { 'zh-CN': '🔄 重新生成镜头', 'en-US': '🔄 Regenerate Shot', 'ja-JP': '🔄 ショット再生成', 'es-ES': '🔄 Regenerar Toma', 'ar-SA': '🔄 إعادة توليد اللقطة' },
    'nle.regenBtn': { 'zh-CN': '🚀 重新生成 AI 镜头', 'en-US': '🚀 Regenerate AI Shot', 'ja-JP': '🚀 AIショット再生成', 'es-ES': '🚀 Regenerar Toma IA', 'ar-SA': '🚀 إعادة توليد لقطة AI' },
    'nle.emptyHint': { 'zh-CN': '输入 Run ID 并点击 "Load Run" 一键装配时间线', 'en-US': 'Enter a Run ID and click "Load Run" to auto-assemble the timeline', 'ja-JP': 'Run IDを入力して「Run を読み込む」をクリック', 'es-ES': 'Ingrese un Run ID y haga clic en "Cargar Ejecución"', 'ar-SA': 'أدخل Run ID وانقر على "تحميل التشغيل"' },
    'nle.propEmptyHint': { 'zh-CN': '在时间轴上点击一个 Clip 即可编辑其属性', 'en-US': 'Click a clip on the timeline to edit its properties', 'ja-JP': 'タイムライン上のクリップをクリックしてプロパティを編集', 'es-ES': 'Haz clic en un clip del timeline para editar sus propiedades', 'ar-SA': 'انقر على مقطع في الجدول الزمني لتعديل خصائصه' },

    // ── Novels (extended) ────────────────────────────────────────────────────────
    'novels.edit': { 'zh-CN': '编辑小说', 'en-US': 'Edit Novel', 'ja-JP': '小説を編集', 'es-ES': 'Editar Novela', 'ar-SA': 'تعديل الرواية' },
    'novels.newTranslation': { 'zh-CN': '新建转译工程', 'en-US': 'New Translation Project', 'ja-JP': '新規翻訳プロジェクト', 'es-ES': 'Nuevo Proyecto de Traducción', 'ar-SA': 'مشروع ترجمة جديد' },
    'novels.novelDetail': { 'zh-CN': '小说详情', 'en-US': 'Novel Details', 'ja-JP': '小説詳細', 'es-ES': 'Detalles de Novela', 'ar-SA': 'تفاصيل الرواية' },
    'novels.chapterList': { 'zh-CN': '章节列表', 'en-US': 'Chapters', 'ja-JP': '章リスト', 'es-ES': 'Lista de Capítulos', 'ar-SA': 'قائمة الفصول' },
    'novels.filmCrew': { 'zh-CN': '影视团队', 'en-US': 'Production Crew', 'ja-JP': '制作チーム', 'es-ES': 'Equipo de Producción', 'ar-SA': 'طاقم الإنتاج' },
    'novels.entityExtract': { 'zh-CN': '实体抽离', 'en-US': 'Entity Extraction', 'ja-JP': 'エンティティ抽出', 'es-ES': 'Extracción de Entidades', 'ar-SA': 'استخراج الكيانات' },

    // ── Chapter ──────────────────────────────────────────────────────────────────
    'chapter.previewResult': { 'zh-CN': '预览结果', 'en-US': 'Preview', 'ja-JP': 'プレビュー', 'es-ES': 'Vista Previa', 'ar-SA': 'معاينة' },
    'chapter.revisionHistory': { 'zh-CN': '修订历史', 'en-US': 'Revision History', 'ja-JP': '改訂履歴', 'es-ES': 'Historial de Revisiones', 'ar-SA': 'تاريخ المراجعات' },
    'chapter.aiExpandLog': { 'zh-CN': 'AI 扩写日志', 'en-US': 'AI Expand Log', 'ja-JP': 'AI展開ログ', 'es-ES': 'Registro de Expansión IA', 'ar-SA': 'سجل التوسيع بالذكاء الاصطناعي' },
    'chapter.chapterMgmt': { 'zh-CN': '章节管理', 'en-US': 'Chapter Management', 'ja-JP': '章管理', 'es-ES': 'Gestión de Capítulos', 'ar-SA': 'إدارة الفصول' },
    'chapter.workspace': { 'zh-CN': '章节工作区', 'en-US': 'Chapter Workspace', 'ja-JP': '章ワークスペース', 'es-ES': 'Área de Trabajo', 'ar-SA': 'مساحة عمل الفصل' },

    // ── KB (extended) ────────────────────────────────────────────────────────────
    'kb.basicInfo': { 'zh-CN': '📋 基本信息', 'en-US': '📋 Basic Info', 'ja-JP': '📋 基本情報', 'es-ES': '📋 Info Básica', 'ar-SA': '📋 المعلومات الأساسية' },
    'kb.sourceFile': { 'zh-CN': '📄 源文件', 'en-US': '📄 Source File', 'ja-JP': '📄 ソースファイル', 'es-ES': '📄 Archivo Fuente', 'ar-SA': '📄 الملف المصدر' },
    'kb.bindingMgmt': { 'zh-CN': '🔗 绑定管理', 'en-US': '🔗 Binding Mgmt', 'ja-JP': '🔗 バインディング管理', 'es-ES': '🔗 Gestión de Vinculación', 'ar-SA': '🔗 إدارة الربط' },
    'kb.collections': { 'zh-CN': '集合管理', 'en-US': 'Collections', 'ja-JP': 'コレクション管理', 'es-ES': 'Gestión de Colecciones', 'ar-SA': 'إدارة المجموعات' },
    'kb.versions': { 'zh-CN': 'KB 版本', 'en-US': 'KB Versions', 'ja-JP': 'KBバージョン', 'es-ES': 'Versiones KB', 'ar-SA': 'إصدارات KB' },
    'kb.docImport': { 'zh-CN': '文档导入', 'en-US': 'Doc Import', 'ja-JP': 'ドキュメントインポート', 'es-ES': 'Importar Documentos', 'ar-SA': 'استيراد المستندات' },

    // ── Roles ────────────────────────────────────────────────────────────────────
    'role.title': { 'zh-CN': '角色配置中心', 'en-US': 'Role Config Center', 'ja-JP': 'ロール設定センター', 'es-ES': 'Centro de Configuración de Roles', 'ar-SA': 'مركز تكوين الأدوار' },
    'role.roles': { 'zh-CN': '职业定义', 'en-US': 'Role Definitions', 'ja-JP': '職業定義', 'es-ES': 'Definiciones de Roles', 'ar-SA': 'تعريفات الأدوار' },
    'role.skills': { 'zh-CN': '技能注册', 'en-US': 'Skill Registry', 'ja-JP': 'スキル登録', 'es-ES': 'Registro de Habilidades', 'ar-SA': 'سجل المهارات' },
    'role.scope': { 'zh-CN': '适用范围', 'en-US': 'Scope', 'ja-JP': '適用範囲', 'es-ES': 'Alcance', 'ar-SA': 'النطاق' },
    'role.preview': { 'zh-CN': '预览测试', 'en-US': 'Preview & Test', 'ja-JP': 'プレビュー&テスト', 'es-ES': 'Vista Previa y Prueba', 'ar-SA': 'معاينة واختبار' },

    // ── Persona ──────────────────────────────────────────────────────────────────
    'persona.create': { 'zh-CN': '创建 Persona', 'en-US': 'Create Persona', 'ja-JP': 'ペルソナを作成', 'es-ES': 'Crear Persona', 'ar-SA': 'إنشاء شخصية' },
    'persona.library': { 'zh-CN': 'Persona 人员库', 'en-US': 'Persona Library', 'ja-JP': 'ペルソナライブラリ', 'es-ES': 'Biblioteca de Personas', 'ar-SA': 'مكتبة الشخصيات' },
    'persona.list': { 'zh-CN': 'Persona 列表', 'en-US': 'Persona List', 'ja-JP': 'ペルソナリスト', 'es-ES': 'Lista de Personas', 'ar-SA': 'قائمة الشخصيات' },
    'persona.preview': { 'zh-CN': 'Persona 预览', 'en-US': 'Persona Preview', 'ja-JP': 'ペルソナプレビュー', 'es-ES': 'Vista Previa de Persona', 'ar-SA': 'معاينة الشخصية' },

    // ── Runs (extended) ──────────────────────────────────────────────────────────
    'runs.createRun': { 'zh-CN': '创建 Task / Run', 'en-US': 'Create Task / Run', 'ja-JP': 'タスク / Run を作成', 'es-ES': 'Crear Tarea / Run', 'ar-SA': 'إنشاء مهمة / تشغيل' },
    'runs.loadObs': { 'zh-CN': '加载运行观测', 'en-US': 'Load Observability', 'ja-JP': '実行観測を読込', 'es-ES': 'Cargar Observabilidad', 'ar-SA': 'تحميل المراقبة' },
    'runs.taskList': { 'zh-CN': '任务列表', 'en-US': 'Task List', 'ja-JP': 'タスクリスト', 'es-ES': 'Lista de Tareas', 'ar-SA': 'قائمة المهام' },

    // ── Models (extended) ────────────────────────────────────────────────────────
    'models.profiles': { 'zh-CN': '模型资产', 'en-US': 'Model Assets', 'ja-JP': 'モデルプロファイル', 'es-ES': 'Activos de Modelos', 'ar-SA': 'أصول النماذج' },
    'models.routingRules': { 'zh-CN': '映射规则', 'en-US': 'Routing Rules', 'ja-JP': 'ルーティングルール', 'es-ES': 'Reglas de Enrutamiento', 'ar-SA': 'قواعد التوجيه' },
    'models.modelList': { 'zh-CN': '接入模型列表目录', 'en-US': 'Model Catalog', 'ja-JP': 'モデルカタログ', 'es-ES': 'Catálogo de Modelos', 'ar-SA': 'كتالوج النماذج' },
    'models.providerApi': { 'zh-CN': 'Provider API 接入', 'en-US': 'Provider API Config', 'ja-JP': 'プロバイダAPI設定', 'es-ES': 'Config. de API de Proveedor', 'ar-SA': 'إعداد API المزود' },
    'models.capabilityList': { 'zh-CN': '模型能力清单与探测', 'en-US': 'Model Capabilities', 'ja-JP': 'モデル能力一覧', 'es-ES': 'Capacidades del Modelo', 'ar-SA': 'قدرات النموذج' },
    'models.diagReport': { 'zh-CN': '诊断报告与建议', 'en-US': 'Diagnosis Report', 'ja-JP': '診断レポート', 'es-ES': 'Informe de Diagnóstico', 'ar-SA': 'تقرير التشخيص' },
    'models.suggestedConfig': { 'zh-CN': '推荐配置预览', 'en-US': 'Suggested Config Preview', 'ja-JP': '推奨設定プレビュー', 'es-ES': 'Vista Previa de Configuración', 'ar-SA': 'معاينة الإعداد المقترح' },
    'models.coreRouting': { 'zh-CN': '全局核心业务路由配置', 'en-US': 'Global Core Routing', 'ja-JP': 'グローバルコアルーティング', 'es-ES': 'Enrutamiento Global Principal', 'ar-SA': 'التوجيه الأساسي العالمي' },

    // ── Notifications ────────────────────────────────────────────────────────────
    'notifications.smtp': { 'zh-CN': '📧 SMTP 邮件', 'en-US': '📧 SMTP Email', 'ja-JP': '📧 SMTPメール', 'es-ES': '📧 Correo SMTP', 'ar-SA': '📧 البريد SMTP' },
    'notifications.title': { 'zh-CN': '通知中心', 'en-US': 'Notification Center', 'ja-JP': '通知センター', 'es-ES': 'Centro de Notificaciones', 'ar-SA': 'مركز الإشعارات' },

    // ── Translation Project ──────────────────────────────────────────────────────
    'trans.progress': { 'zh-CN': '转译进度', 'en-US': 'Translation Progress', 'ja-JP': '翻訳進度', 'es-ES': 'Progreso de Traducción', 'ar-SA': 'تقدم الترجمة' },
    'trans.script': { 'zh-CN': '转译剧本', 'en-US': 'Translated Script', 'ja-JP': '翻訳台本', 'es-ES': 'Guión Traducido', 'ar-SA': 'النص المترجم' },
    'trans.consistency': { 'zh-CN': '一致性中心', 'en-US': 'Consistency Center', 'ja-JP': '一貫性センター', 'es-ES': 'Centro de Consistencia', 'ar-SA': 'مركز الاتساق' },
    'trans.entityVariants': { 'zh-CN': '实体变体表', 'en-US': 'Entity Variants', 'ja-JP': 'エンティティバリアント', 'es-ES': 'Variantes de Entidades', 'ar-SA': 'متغيرات الكيانات' },

    // ── Auth (extended) ──────────────────────────────────────────────────────────
    'auth.newUser': { 'zh-CN': '新增用户', 'en-US': 'New User', 'ja-JP': '新規ユーザー', 'es-ES': 'Nuevo Usuario', 'ar-SA': 'مستخدم جديد' },
    'auth.editUser': { 'zh-CN': '编辑用户', 'en-US': 'Edit User', 'ja-JP': 'ユーザー編集', 'es-ES': 'Editar Usuario', 'ar-SA': 'تعديل المستخدم' },
    'auth.permRules': { 'zh-CN': '路由权限规则', 'en-US': 'Route Permission Rules', 'ja-JP': 'ルートパーミッションルール', 'es-ES': 'Reglas de Permisos de Rutas', 'ar-SA': 'قواعد أذونات التوجيه' },

    // ── Script Workflow ──────────────────────────────────────────────────────────
    'script.title':         { 'zh-CN': '剧本转换',     'en-US': 'Script Conversion' },
    'script.formatDetect':  { 'zh-CN': '格式检测',     'en-US': 'Format Detect' },
    'script.novelToScript': { 'zh-CN': '剧本转换',     'en-US': 'Novel→Script' },
    'script.normalize':     { 'zh-CN': '剧本标准化',   'en-US': 'Script Normalize' },
    'script.granularity':   { 'zh-CN': '切分粒度',     'en-US': 'Granularity' },
    'script.coarse':        { 'zh-CN': '粗粒度',       'en-US': 'Coarse' },
    'script.normal':        { 'zh-CN': '普通',         'en-US': 'Normal' },
    'script.fine':          { 'zh-CN': '细粒度',       'en-US': 'Fine' },
    'script.scenes':        { 'zh-CN': '场景列表',     'en-US': 'Scenes' },

    // ── Script (extended) ────────────────────────────────────────────────────────
    'script.loadExisting':  { 'zh-CN': '加载已有剧本', 'en-US': 'Load Existing' },
    'script.regenerate':    { 'zh-CN': '重新生成（消耗 Token）', 'en-US': 'Regenerate (Uses Token)' },
    'script.version':       { 'zh-CN': '版本',         'en-US': 'Version' },
    'script.cachedHit':     { 'zh-CN': '命中缓存',     'en-US': 'Cache Hit' },

    // ── World Model ──────────────────────────────────────────────────────────────
    'world.title':          { 'zh-CN': '世界模型抽离', 'en-US': 'World Model Extract' },
    'world.extractionLevel':{ 'zh-CN': '提取级别',     'en-US': 'Extraction Level' },
    'world.characters':     { 'zh-CN': '人物',         'en-US': 'Characters' },
    'world.locations':      { 'zh-CN': '场景',         'en-US': 'Locations' },
    'world.props':          { 'zh-CN': '道具',         'en-US': 'Props' },
    'world.beats':          { 'zh-CN': '剧情节拍',     'en-US': 'Story Beats' },
    'world.styleHints':     { 'zh-CN': '风格提示',     'en-US': 'Style Hints' },
    'world.extract':        { 'zh-CN': '开始抽离',     'en-US': 'Extract' },
    'world.regenerate':     { 'zh-CN': '重新抽离（消耗 Token）', 'en-US': 'Regenerate (Uses Token)' },
    'world.loadExisting':   { 'zh-CN': '加载已有世界模型', 'en-US': 'Load Existing' },
    'world.writeToMapping': { 'zh-CN': '写入实体对应表','en-US': 'Write to Entity Mapping' },

    // ── Entity Mapping ───────────────────────────────────────────────────────────
    'entity.mappingTitle':  { 'zh-CN': '实体对应表',   'en-US': 'Entity Mapping' },
    'entity.canonicalName': { 'zh-CN': '规范名',       'en-US': 'Canonical Name' },
    'entity.status':        { 'zh-CN': '一致性状态',   'en-US': 'Continuity Status' },
    'entity.merge':         { 'zh-CN': '合并',         'en-US': 'Merge' },
    'entity.translate':     { 'zh-CN': '补译名（本土化）',       'en-US': 'Localized Name Fill' },
    'entity.aliases':       { 'zh-CN': '别名',         'en-US': 'Aliases' },
    'entity.translations':  { 'zh-CN': '多语言译名',   'en-US': 'Translations' },
    'entity.evidence':      { 'zh-CN': '原文证据',     'en-US': 'Evidence' },
    'entity.build':         { 'zh-CN': '生成实体对应表','en-US': 'Build Mapping' },
    'entity.locked':        { 'zh-CN': '已锁定',       'en-US': 'Locked' },
    'entity.namingPolicy':  { 'zh-CN': '命名策略',     'en-US': 'Naming Policy' },
    'entity.rationale':     { 'zh-CN': '命名理由',     'en-US': 'Rationale' },

    // ── Name Localization ─────────────────────────────────────────────────────────
    'entity.nameLocalization': { 'zh-CN': '姓名本地化建议', 'en-US': 'Name Localization' },
    'entity.suggestNames':     { 'zh-CN': 'AI 建议命名（消耗 Token）', 'en-US': 'AI Suggest Names (Uses Token)' },
    'entity.cultureProfile':   { 'zh-CN': '文化背景',     'en-US': 'Culture Profile' },
    'entity.applyAndLock':     { 'zh-CN': '应用并锁定',   'en-US': 'Apply & Lock' },

    // ── SkillRun ──────────────────────────────────────────────────────────────────
    'run.title':            { 'zh-CN': 'LLM 运行记录', 'en-US': 'Skill Runs' },
    'run.status':           { 'zh-CN': '状态',          'en-US': 'Status' },
    'run.skillId':          { 'zh-CN': '技能ID',         'en-US': 'Skill ID' },
    'run.inputHash':        { 'zh-CN': '输入哈希',       'en-US': 'Input Hash' },
    'run.tokenUsage':       { 'zh-CN': 'Token 用量',     'en-US': 'Token Usage' },
    'run.costEstimate':     { 'zh-CN': '费用估算',       'en-US': 'Cost Estimate' },
    'run.cached':           { 'zh-CN': '命中缓存',       'en-US': 'Cache Hit' },
}


// ─── Composable ────────────────────────────────────────────────────────────────

export function useI18n() {
    const localeStore = useLocaleStore()

    function t(key: string, fallback?: string): string {
        const entry = translations[key]
        if (!entry) return fallback ?? key
        return entry[localeStore.locale] ?? entry['zh-CN'] ?? fallback ?? key
    }

    return {
        t,
        locale: computed(() => localeStore.locale),
        setLocale: localeStore.setLocale,
    }
}

package cn.csla.mobile

import android.app.Activity
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.pdf.PdfRenderer
import android.os.Bundle
import android.os.ParcelFileDescriptor
import android.text.InputType
import android.view.WindowManager
import android.widget.*
import com.chaquo.python.Python
import org.json.JSONObject
import java.io.File
import java.util.concurrent.Executors

/** Android PdfRenderer provides offline viewing and citation page navigation. */
class PdfActivity : Activity() {
    private val worker = Executors.newSingleThreadExecutor()
    private var renderer: PdfRenderer? = null
    private var descriptor: ParcelFileDescriptor? = null
    private var bitmap: Bitmap? = null
    private lateinit var image: ImageView
    private lateinit var label: TextView
    private lateinit var pageInput: EditText
    private var pageIndex = 0

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        root.setOnApplyWindowInsetsListener { view, insets ->
            view.setPadding(insets.systemWindowInsetLeft, insets.systemWindowInsetTop,
                insets.systemWindowInsetRight, insets.systemWindowInsetBottom)
            insets
        }
        val bar = LinearLayout(this)
        fun button(text: String, action: () -> Unit) {
            bar.addView(Button(this).apply { this.text = text; setOnClickListener { action() } },
                LinearLayout.LayoutParams(0, -2, 1f))
        }
        button("返回") { finish() }
        button("上页") { render(pageIndex - 1) }
        button("下页") { render(pageIndex + 1) }
        pageInput = EditText(this).apply {
            inputType = InputType.TYPE_CLASS_NUMBER
            hint = "页码"
            setEms(3)
        }
        bar.addView(pageInput, LinearLayout.LayoutParams(0, -2, .8f))
        button("跳转") { render((pageInput.text.toString().toIntOrNull() ?: 1) - 1) }
        label = TextView(this).apply { setPadding(16, 12, 16, 12); text = "正在读取本地 PDF…" }
        image = ImageView(this).apply { adjustViewBounds = true }
        val scroll = ScrollView(this).apply { addView(image) }
        root.addView(bar); root.addView(label)
        root.addView(scroll, LinearLayout.LayoutParams(-1, 0, 1f))
        setContentView(root)
        worker.execute {
            try {
                val info = JSONObject(Python.getInstance().getModule("mobile_runtime")
                    .callAttr("source_info", intent.getStringExtra("material_id") ?: "").toString())
                require(info.getBoolean("pdf"))
                descriptor = ParcelFileDescriptor.open(File(info.getString("path")),
                    ParcelFileDescriptor.MODE_READ_ONLY)
                renderer = PdfRenderer(descriptor!!)
                runOnUiThread {
                    if (!isFinishing && !isDestroyed) render(intent.getIntExtra("page", 1) - 1)
                }
            } catch (_: Exception) {
                runOnUiThread { label.text = "PDF 不能打开；扫描件仍可查看，异常或加密文件请换一份后导入。" }
            }
        }
    }

    private fun render(wanted: Int) {
        worker.execute {
            val pdf = renderer ?: return@execute
            if (pdf.pageCount == 0) return@execute
            val index = wanted.coerceIn(0, pdf.pageCount - 1)
            try {
                val next = pdf.openPage(index).use { page ->
                    val width = minOf(1600, maxOf(800, resources.displayMetrics.widthPixels))
                    val height = (width.toDouble() * page.height / page.width).toInt().coerceIn(1, 5000)
                    Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888).also {
                        it.eraseColor(Color.WHITE)
                        page.render(it, null, null, PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY)
                    }
                }
                runOnUiThread {
                    if (isFinishing || isDestroyed) { next.recycle(); return@runOnUiThread }
                    val old = bitmap
                    bitmap = next; image.setImageBitmap(next); old?.recycle()
                    pageIndex = index
                    label.text = "PDF 第 ${index + 1} / ${pdf.pageCount} 页 · 文件保存在手机"
                    pageInput.setText((index + 1).toString())
                }
            } catch (_: Exception) { runOnUiThread { label.text = "此页无法渲染，请尝试其他页" } }
        }
    }

    override fun onDestroy() {
        worker.execute { renderer?.close(); descriptor?.close(); renderer = null }
        worker.shutdown()
        image.setImageDrawable(null); bitmap?.recycle(); bitmap = null
        super.onDestroy()
    }
}

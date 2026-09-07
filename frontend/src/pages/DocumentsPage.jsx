import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listDocuments, retryDocument, uploadDocument } from "../api.js";

const STATUS_LABEL = {
  pending: "排队中",
  parsing: "解析中",
  chunking: "切分中",
  embedding: "向量化中",
  indexing: "索引中",
  ready: "已完成",
  failed: "处理失败",
};

const STATUS_DOT = {
  pending: "queued",
  parsing: "working",
  chunking: "working",
  embedding: "working",
  indexing: "working",
  ready: "ready",
  failed: "failed",
};

function DocIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M14 2v6h6M16 13H8M16 17H8M10 9H8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

export default function DocumentsPage() {
  const [documents, setDocuments] = useState([]);
  const [message, setMessage] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [ocr, setOcr] = useState(false);

  const refresh = async () => {
    const rows = await listDocuments();
    setDocuments(rows);
    const active = rows.some((row) => STATUS_DOT[row.status] === "working" || row.status === "pending");
    if (active) setTimeout(refresh, 2500);
  };

  useEffect(() => {
    refresh().catch(console.error);
  }, []);

  const upload = async (file) => {
    if (!file) return;
    try {
      await uploadDocument(file, { ocr });
      setMessage("上传成功，正在后台处理");
      refresh();
    } catch (error) {
      setMessage(error.message);
    }
  };

  const onRetry = async (id) => {
    await retryDocument(id);
    refresh();
  };

  return (
    <div className="docs-layout">
      <aside className="sidebar">
        <Link to="/" className="side-link">
          <DocIcon />
          企业知识库
        </Link>
        <Link to="/" className="new-chat secondary">
          ← 返回对话
        </Link>
      </aside>

      <main className="docs-main">
        <header className="docs-header">
          <h1>文档管理</h1>
          <p>上传 PDF / 图片后自动解析、切分并建立索引，完成后即可在对话中引用。</p>
        </header>

        <div className="upload-options">
          <label className="ocr-toggle">
            <input type="checkbox" checked={ocr} onChange={(event) => setOcr(event.target.checked)} />
            扫描件 / 复杂彩页（强制 MinerU OCR，仅对 PDF 与图片生效）
          </label>
        </div>

        <label
          className={`upload-zone ${dragOver ? "dragover" : ""}`}
          onDragOver={(event) => {
            event.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragOver(false);
            upload(event.dataTransfer.files[0]);
          }}
        >
          <input
            type="file"
            accept=".pdf,.docx,.pptx,.xlsx,.md,.markdown,.txt,.html,.htm,.csv,.json,.png,.jpg,.jpeg"
            onChange={(event) => upload(event.target.files[0])}
          />
          <div className="upload-icon">
            <DocIcon />
          </div>
          <div className="upload-title">点击上传或拖拽文档 / 图片到此处</div>
          <div className="upload-sub">
            支持 PDF / Word / PPT / Excel / Markdown / TXT / HTML / CSV / JSON / 图片(PNG/JPG)，上传后统一转为 Markdown
          </div>
          {message && <div className="upload-message">{message}</div>}
        </label>

        <section className="doc-list">
          <div className="doc-list-title">文档列表</div>
          {documents.length === 0 && <div className="doc-empty">还没有文档，先上传一份 PDF 或图片吧。</div>}
          {documents.map((document) => (
            <div className="doc-card" key={document.id}>
              <div className="doc-icon">
                <DocIcon />
              </div>
              <div className="doc-info">
                <div className="doc-name">{document.title}</div>
                {document.page_count ? (
                  <div className="doc-meta">{document.page_count} 页 · {document.filename}</div>
                ) : (
                  <div className="doc-meta">{document.filename}</div>
                )}
                {document.error_message && <div className="doc-error">{document.error_message}</div>}
              </div>
              <div className="doc-side">
                <span className={`status status-${STATUS_DOT[document.status] || "queued"}`}>
                  <i />
                  {STATUS_LABEL[document.status] || document.status}
                </span>
                {document.status === "failed" && (
                  <button className="retry" onClick={() => onRetry(document.id)}>
                    重试
                  </button>
                )}
              </div>
            </div>
          ))}
        </section>
      </main>
    </div>
  );
}

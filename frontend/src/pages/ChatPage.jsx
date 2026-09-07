import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  createConversation,
  getMessages,
  listConversations,
  streamChat,
  submitFeedback,
} from "../api.js";

const SUGGESTIONS = [
  "ZB-100 打印机的保修期是多久？",
  "ZB-100 和 ZB-200 的保修有什么区别？",
  "打印机卡纸了应该怎么办？",
  "如何申请保修？",
];

function SparkleIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M12 2l1.8 5.6L19.5 9l-5.7 1.4L12 16l-1.8-5.6L4.5 9l5.7-1.4L12 2z"
        fill="currentColor"
      />
      <path d="M19 14l.8 2.2L22 17l-2.2.8L19 20l-.8-2.2L16 17l2.2-.8L19 14z" fill="currentColor" />
    </svg>
  );
}

function RichText({ text }) {
  const parts = String(text || "").split(/\*\*(.+?)\*\*/g);
  return parts.map((part, index) => (index % 2 === 1 ? <strong key={index}>{part}</strong> : part));
}

export default function ChatPage() {
  const [conversations, setConversations] = useState([]);
  const [conversationId, setConversationId] = useState(null);
  const [conversationTitle, setConversationTitle] = useState("新对话");
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const textareaRef = useRef(null);
  const bottomRef = useRef(null);

  const refreshConversations = async () => {
    const rows = await listConversations();
    setConversations(rows);
    return rows;
  };

  useEffect(() => {
    refreshConversations().catch(console.error);
  }, []);

  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, loading]);

  const openConversation = async (conversation) => {
    setConversationId(conversation.id);
    setConversationTitle(conversation.title || "新对话");
    setMessages(await getMessages(conversation.id));
  };

  const newConversation = async () => {
    const conversation = await createConversation();
    const rows = await refreshConversations();
    setConversationId(conversation.id);
    setConversationTitle(conversation.title || "新对话");
    setMessages([]);
    setConversations(rows);
  };

  const send = async (rawText) => {
    const text = (rawText ?? input).trim();
    if (!text || loading) return;
    setInput("");
    setLoading(true);

    let currentId = conversationId;
    let currentTitle = conversationTitle;
    const optimisticMessages = [
      ...messages,
      { role: "user", content: text },
      { role: "assistant", content: "", streaming: true },
    ];
    setMessages(optimisticMessages);

    let assembled = "";
    try {
      await streamChat({
        message: text,
        conversationId: currentId,
        onStart: (data) => {
          currentId = data.conversation_id;
        },
        onToken: (token) => {
          assembled += token;
          setMessages([
            ...optimisticMessages.slice(0, -1),
            { role: "assistant", content: assembled, streaming: true },
          ]);
        },
        onDone: (data) => {
          currentId = data.conversation_id;
          assembled = data.answer || assembled;
        },
        onError: (error) => {
          assembled += `\n[错误] ${error}`;
        },
      });
    } catch (error) {
      assembled += `\n[错误] ${error.message}`;
    }

    setConversationId(currentId);
    setLoading(false);
    const rows = await refreshConversations();
    const active = rows.find((item) => item.id === currentId);
    if (active) currentTitle = active.title;
    setConversationTitle(currentTitle);
    if (currentId) {
      setMessages(await getMessages(currentId));
    }
  };

  const feedback = async (message, rating) => {
    if (!message.id) return;
    try {
      await submitFeedback({ messageId: message.id, rating, comment: "" });
    } catch (error) {
      console.error(error);
    }
  };

  const empty = !conversationId && messages.length === 0;

  return (
    <div className="chat-layout">
      <aside className="sidebar">
        <Link to="/" className="side-link">
          <SparkleIcon />
          企业知识库
        </Link>
        <button className="new-chat" onClick={newConversation}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
            <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
          新对话
        </button>

        <div className="side-section">最近</div>
        <div className="conversation-list">
          {conversations.length === 0 && (
            <div className="conversation-empty">还没有历史会话</div>
          )}
          {conversations.map((conversation) => (
            <button
              key={conversation.id}
              className={`conversation-item ${conversation.id === conversationId ? "active" : ""}`}
              onClick={() => openConversation(conversation)}
              title={conversation.title || "新对话"}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
                <path
                  d="M21 11.5a8.38 8.38 0 01-.9 3.8 8.5 8.5 0 01-7.6 4.7 8.38 8.38 0 01-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 01-.9-3.8 8.5 8.5 0 014.7-7.6 8.38 8.38 0 013.8-.9h.5a8.48 8.48 0 018 8v.5z"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              <span>{conversation.title || "新对话"}</span>
            </button>
          ))}
        </div>

        <div className="sidebar-footer">
          <Link to="/documents" className="side-link small">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
              <path
                d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6z"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path d="M14 2v6h6M16 13H8M16 17H8M10 9H8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
            文档管理
          </Link>
        </div>
      </aside>

      <main className="chat-main">
        {conversationId && (
          <header className="chat-header">
            <span className="chat-title">{conversationTitle || "新对话"}</span>
          </header>
        )}

        {empty ? (
          <section className="welcome">
            <div className="welcome-logo">
              <SparkleIcon />
            </div>
            <h1>你好，我是你的企业知识库助手</h1>
            <p>上传产品手册与制度文档后，我可以基于文档回答你的问题，并支持连续追问。</p>
            <div className="suggestions">
              {SUGGESTIONS.map((suggestion) => (
                <button key={suggestion} onClick={() => send(suggestion)}>
                  {suggestion}
                </button>
              ))}
            </div>
          </section>
        ) : (
          <section className="messages">
            <div className="message-column">
              {messages.map((message, index) => (
                <div className={`message ${message.role}`} key={index}>
                  {message.role === "assistant" && (
                    <div className="avatar" aria-hidden>
                      知
                    </div>
                  )}
                  <div className="message-body">
                    {message.role === "assistant" ? (
                      <>
                        <RichText text={message.content || (message.streaming ? "正在思考…" : "")} />
                        {message.citations?.length > 0 && (
                          <div className="citations">
                            {message.citations.map((citation) => (
                              <span className="citation-chip" key={citation.chunk_id}>
                                📄 {citation.document_title}
                                {citation.page > 0
                                  ? ` · 第 ${citation.page} 页`
                                  : citation.section
                                    ? ` · ${citation.section}`
                                    : ""}
                              </span>
                            ))}
                          </div>
                        )}
                        {message.id && !message.streaming && (
                          <div className="feedback">
                            <button title="有帮助" onClick={() => feedback(message, "up")}>
                              👍
                            </button>
                            <button title="没帮助" onClick={() => feedback(message, "down")}>
                              👎
                            </button>
                          </div>
                        )}
                      </>
                    ) : (
                      <div className="user-bubble">
                        <RichText text={message.content} />
                      </div>
                    )}
                  </div>
                </div>
              ))}
              <div ref={bottomRef} />
            </div>
          </section>
        )}

        <footer className="composer-wrap">
          <div className="composer">
            <textarea
              ref={textareaRef}
              rows={1}
              value={input}
              placeholder="问点想问的，Enter 发送，Shift + Enter 换行"
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  send();
                }
              }}
            />
            <button className="send" onClick={() => send()} disabled={!input.trim() || loading} title="发送">
              {loading ? (
                <span className="spinner" />
              ) : (
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
                  <path
                    d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              )}
            </button>
          </div>
          <div className="composer-hint">回答基于已上传文档生成，请核对引用来源</div>
        </footer>
      </main>
    </div>
  );
}

import React from 'react';
import { Trash2, FileText, CheckCircle2, AlertCircle, Loader2, Sparkles } from 'lucide-react';

export default function DocumentList({ 
  documents, 
  selectedDocId, 
  onSelectDocument, 
  onDeleteDocument,
  apiBaseUrl 
}) {

  const formatBytes = (bytes) => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  const formatDate = (dateString) => {
    const date = new Date(dateString);
    return date.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  const handleDelete = async (e, id) => {
    e.stopPropagation(); // Prevent selecting the document when clicking delete
    if (window.confirm("Are you sure you want to delete this document and all its text embeddings?")) {
      try {
        const response = await fetch(`${apiBaseUrl}/documents/${id}`, {
          method: "DELETE"
        });
        if (response.ok) {
          onDeleteDocument(id);
        } else {
          alert("Failed to delete document.");
        }
      } catch (err) {
        console.error("Error deleting document:", err);
        alert("An error occurred while deleting the document.");
      }
    }
  };

  return (
    <div className="glass-panel p-6 flex flex-col h-full lg:h-auto lg:flex-1 lg:min-h-0 transition-colors duration-300">
      <div className="flex items-center justify-between mb-4 shrink-0">
        <h2 className="font-outfit text-lg font-bold text-claude-text-primary flex items-center space-x-2">
          <FileText className="h-5 w-5 text-claude-accent" />
          <span>Knowledge Base</span>
        </h2>
        <span className="text-xs bg-claude-sidebar border border-claude-border text-claude-text-secondary px-2 py-0.5 rounded-full font-mono transition-colors duration-300">
          {documents.length} files
        </span>
      </div>

      {/* Select All Option */}
      {documents.length > 0 && (
        <div 
          onClick={() => onSelectDocument(null)}
          className={`flex items-center justify-between p-3 mb-3 rounded-xl border cursor-pointer transition-all duration-200 ${
            selectedDocId === null 
              ? "border-claude-accent/50 bg-claude-accent-bg text-claude-accent font-semibold" 
              : "border-claude-border bg-claude-sidebar/20 text-claude-text-secondary hover:border-claude-border hover:bg-claude-sidebar/40 hover:text-claude-text-primary"
          }`}
        >
          <div className="flex items-center space-x-2.5">
            <Sparkles className={`h-4.5 w-4.5 ${selectedDocId === null ? 'text-claude-accent' : 'text-claude-text-secondary'}`} />
            <span className="text-sm font-medium">Search All Documents</span>
          </div>
          <span className="text-[10px] uppercase font-mono tracking-wider font-semibold opacity-85">Global</span>
        </div>
      )}

      {/* Document List */}
      <div className="flex-1 overflow-y-auto space-y-2 lg:max-h-none pr-1">
        {documents.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-48 border border-dashed border-claude-border rounded-xl text-claude-text-secondary p-4 text-center transition-colors duration-300">
            <FileText className="h-10 w-10 text-claude-border mb-2 stroke-[1.5]" />
            <p className="text-sm font-medium">No documents uploaded</p>
            <p className="text-xs text-claude-text-secondary/80 mt-1">Upload a PDF to start asking questions.</p>
          </div>
        ) : (
          documents.map((doc) => {
            const isSelected = selectedDocId === doc.id;
            const isProcessing = doc.status === 'processing';
            const isError = doc.status === 'error';
            
            return (
              <div
                key={doc.id}
                onClick={() => !isProcessing && onSelectDocument(doc.id)}
                className={`group flex items-center justify-between p-3 rounded-xl border transition-all duration-200 ${
                  isProcessing 
                    ? "opacity-60 cursor-not-allowed border-claude-border bg-claude-sidebar/10" 
                    : isSelected
                      ? "border-claude-accent bg-claude-accent-bg text-claude-accent font-semibold"
                      : "border-claude-border bg-claude-sidebar/20 hover:border-claude-border hover:bg-claude-sidebar/40 cursor-pointer text-claude-text-primary"
                }`}
              >
                <div className="flex items-center space-x-3 min-w-0 flex-1">
                  <div className={`p-2 rounded-lg transition-colors duration-200 ${
                    isSelected ? 'bg-claude-accent/20 text-claude-accent' : 'bg-claude-card border border-claude-border text-claude-text-secondary'
                  }`}>
                    <FileText className="h-4.5 w-4.5" />
                  </div>
                  
                  <div className="min-w-0 flex-1">
                    <p 
                      className={`text-sm font-medium truncate pr-2 text-claude-text-primary`}
                      title={doc.title || doc.filename}
                    >
                      {doc.title || doc.filename}
                    </p>
                    {doc.author && (
                      <p className="text-[11px] text-claude-accent truncate pr-2 mt-0.5 font-medium" title={doc.author}>
                        By {doc.author}
                      </p>
                    )}
                    <div className="flex items-center space-x-2 text-[10px] text-claude-text-secondary mt-0.5">
                      {doc.title && <span className="truncate max-w-[80px] font-mono text-[9px] text-claude-text-secondary/70" title={doc.filename}>{doc.filename}</span>}
                      {doc.title && <span>•</span>}
                      <span>{formatBytes(doc.file_size)}</span>
                      <span>•</span>
                      <span>{formatDate(doc.uploaded_at)}</span>
                      <span>•</span>
                      {doc.has_context ? (
                        <span className="flex items-center text-purple-600 dark:text-purple-400 bg-purple-500/10 dark:bg-purple-500/20 px-1 rounded text-[9px] font-semibold font-mono tracking-tight" title="Uploaded with Contextual Retrieval">
                          <Sparkles className="h-2.5 w-2.5 mr-0.5 text-purple-500" /> Contextual
                        </span>
                      ) : (
                        <span className="flex items-center text-slate-500 dark:text-slate-400 bg-slate-500/10 dark:bg-slate-500/20 px-1 rounded text-[9px] font-medium font-mono tracking-tight" title="Uploaded without Contextual Retrieval">
                          Standard
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                <div className="flex items-center space-x-2 shrink-0">
                  {/* Status Indicator */}
                  {isProcessing && (
                    <div className="flex items-center space-x-1 text-amber-600 dark:text-amber-400 px-2 py-0.5 rounded-full bg-amber-500/5 text-[10px] font-medium border border-amber-500/20">
                      <Loader2 className="h-3 w-3 animate-spin" />
                      <span>Indexing {doc.processing_progress !== undefined && doc.processing_progress !== null ? `${doc.processing_progress}%` : '0%'}</span>
                    </div>
                  )}

                  {isError && (
                    <div className="flex items-center space-x-1 text-rose-600 dark:text-rose-400 px-2 py-0.5 rounded-full bg-rose-500/5 text-[10px] font-medium border border-rose-500/20">
                      <AlertCircle className="h-3 w-3" />
                      <span>Failed</span>
                    </div>
                  )}

                  {doc.status === 'processed' && (
                    <div className="flex items-center space-x-1 text-emerald-600 dark:text-emerald-400 px-2 py-0.5 rounded-full bg-emerald-500/5 text-[10px] font-medium border border-emerald-500/20">
                      <CheckCircle2 className="h-3 w-3" />
                      <span>Ready</span>
                    </div>
                  )}

                  {/* Delete Button */}
                  <button
                    onClick={(e) => handleDelete(e, doc.id)}
                    className="p-1.5 rounded-lg text-claude-text-secondary hover:text-rose-500 hover:bg-rose-500/5 border border-transparent hover:border-rose-500/10 cursor-pointer transition-all duration-200"
                    title="Delete document"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

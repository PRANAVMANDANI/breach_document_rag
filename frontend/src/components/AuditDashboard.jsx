import React, { useState } from 'react';
import { ShieldCheck, ShieldAlert, Shield, AlertTriangle, Download, ChevronDown, ChevronUp, FileText, ExternalLink, RefreshCw } from 'lucide-react';

export default function AuditDashboard({ document, apiBaseUrl }) {
  const [expandedRiskIdx, setExpandedRiskIdx] = useState(null);
  const [downloading, setDownloading] = useState(false);

  if (!document) {
    return (
      <div className="p-8 flex flex-col items-center justify-center h-full text-center text-claude-text-secondary transition-colors duration-300">
        <Shield className="h-14 w-14 text-claude-border mb-4 stroke-[1.5]" />
        <h3 className="font-outfit font-bold text-claude-text-primary text-base mb-1">No Document Selected</h3>
        <p className="text-sm max-w-md leading-relaxed">Select a specific contract from the knowledge base to view its automated legal risk audit dashboard.</p>
      </div>
    );
  }

  if (document.status === 'processing') {
    return (
      <div className="p-8 flex flex-col items-center justify-center h-full text-center text-claude-text-secondary transition-colors duration-300">
        <RefreshCw className="h-10 w-10 text-claude-accent animate-spin mb-4" />
        <h3 className="font-outfit font-bold text-claude-text-primary text-base mb-1">Analyzing Contract...</h3>
        <p className="text-sm">Analyzing document contents and generating compliance report.</p>
      </div>
    );
  }

  if (document.status === 'error') {
    return (
      <div className="p-8 flex flex-col items-center justify-center h-full text-center text-rose-500 transition-colors duration-300">
        <ShieldAlert className="h-14 w-14 text-rose-400 mb-4 stroke-[1.5]" />
        <h3 className="font-outfit font-bold text-rose-600 dark:text-rose-400 text-base mb-1">Analysis Failed</h3>
        <p className="text-sm max-w-md">{document.error_message || "An error occurred during background ingestion."}</p>
      </div>
    );
  }

  if (!document.has_audit || !document.audit_report) {
    return (
      <div className="p-8 flex flex-col items-center justify-center h-full text-center text-claude-text-secondary transition-colors duration-300">
        <AlertTriangle className="h-14 w-14 text-amber-500 mb-4 stroke-[1.5]" />
        <h3 className="font-outfit font-bold text-claude-text-primary text-base mb-1">No Compliance Audit</h3>
        <p className="text-sm max-w-md leading-relaxed mb-4">This document was processed without a legal compliance audit. Re-upload with 'Deep Compliance Audit' enabled to analyze risks.</p>
      </div>
    );
  }

  if (document.audit_report.is_contract === false) {
    const docType = document.audit_report.document_type || 'UNKNOWN';
    const confidence = Math.round((document.audit_report.confidence || 0.95) * 100);
    const reason = document.audit_report.reason || "The document lacks binding legal obligations, signatures, or defined party obligations typical of a contract.";
    
    return (
      <div className="p-6 flex flex-col items-center justify-center h-full text-center transition-colors duration-300 max-w-md mx-auto my-auto overflow-y-auto">
        <div className="p-3 bg-rose-500/10 border border-rose-500/20 rounded-full mb-4">
          <ShieldAlert className="h-10 w-10 text-rose-500 stroke-[1.5]" />
        </div>
        
        <h3 className="font-outfit font-bold text-claude-text-primary text-base mb-2 flex items-center gap-2">
          <span>⚠️ Document Not Analysable</span>
        </h3>
        
        <div className="bg-claude-sidebar/40 border border-claude-border rounded-xl p-4 w-full text-left my-4 space-y-2.5 transition-colors duration-300">
          <div className="flex justify-between text-xs border-b border-claude-border/50 pb-2">
            <span className="text-claude-text-secondary">LegalEagle identified this document as:</span>
            <span className="font-bold font-mono text-rose-500">{docType}</span>
          </div>
          <div className="flex justify-between text-xs border-b border-claude-border/50 pb-2">
            <span className="text-claude-text-secondary">Confidence:</span>
            <span className="font-bold font-mono text-claude-text-primary">{confidence}%</span>
          </div>
          <div className="text-xs pt-1 text-claude-text-secondary">
            <span className="font-bold text-claude-text-primary">Reason: </span>
            {reason}
          </div>
        </div>
        
        <div className="text-xs text-claude-text-secondary leading-relaxed mb-6 space-y-3">
          <p>LegalEagle only analyses legal contracts, NDAs, and binding agreements.</p>
          <div className="text-left bg-emerald-500/5 border border-emerald-500/10 rounded-xl p-3.5 space-y-2">
            <p className="text-[10px] font-bold uppercase tracking-wider text-emerald-500 mb-1">Please upload one of:</p>
            <div className="grid grid-cols-2 gap-1.5 text-[10px] text-claude-text-primary font-medium">
              <div className="flex items-center gap-1">✅ Non-Disclosure Agreements</div>
              <div className="flex items-center gap-1">✅ Service / Consulting Agreements</div>
              <div className="flex items-center gap-1">✅ Employment Contracts</div>
              <div className="flex items-center gap-1">✅ Lease Deeds</div>
              <div className="flex items-center gap-1 col-span-2">✅ MOUs and Term Sheets</div>
            </div>
          </div>
        </div>
        
        <div className="text-xs text-claude-accent font-semibold flex items-center gap-1 hover:underline cursor-pointer">
          <FileText className="h-3.5 w-3.5" />
          <span>Upload a different document</span>
        </div>
      </div>
    );
  }

  const { overall_score, summary, risks = [] } = document.audit_report;

  // Score styling parameters
  let scoreColorClass = '';
  let scoreBorderClass = '';
  let scoreText = '';
  let scoreIcon = null;

  if (overall_score >= 80) {
    scoreColorClass = 'text-emerald-500 dark:text-emerald-400';
    scoreBorderClass = 'border-emerald-500/20 bg-emerald-500/5';
    scoreText = 'Safe & Standard';
    scoreIcon = <ShieldCheck className="h-5 w-5 text-emerald-500 shrink-0" />;
  } else if (overall_score >= 50) {
    scoreColorClass = 'text-amber-500 dark:text-amber-400';
    scoreBorderClass = 'border-amber-500/20 bg-amber-500/5';
    scoreText = 'Moderate Legal Warning';
    scoreIcon = <AlertTriangle className="h-5 w-5 text-amber-500 shrink-0" />;
  } else {
    scoreColorClass = 'text-rose-500 dark:text-rose-400';
    scoreBorderClass = 'border-rose-500/20 bg-rose-500/5';
    scoreText = 'High Risk - Negotation Advised';
    scoreIcon = <ShieldAlert className="h-5 w-5 text-rose-500 shrink-0" />;
  }

  const handleDownloadReport = async () => {
    setDownloading(true);
    try {
      const response = await fetch(`${apiBaseUrl}/documents/${document.id}/report`);
      if (!response.ok) {
        throw new Error("Failed to download report PDF.");
      }
      
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = window.document.createElement('a');
      a.href = url;
      a.download = `LegalEagle_Audit_${document.filename}`;
      window.document.body.appendChild(a);
      a.click();
      window.document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
    } catch (err) {
      console.error(err);
      alert("Error downloading PDF report: " + err.message);
    } finally {
      setDownloading(false);
    }
  };

  const toggleRiskExpand = (idx) => {
    setExpandedRiskIdx(expandedRiskIdx === idx ? null : idx);
  };

  return (
    <div className="p-6 flex flex-col h-full overflow-y-auto transition-colors duration-300">
      {/* Title & Document Info */}
      <div className="flex items-center justify-between pb-4 border-b border-claude-border mb-4 shrink-0 transition-colors duration-300">
        <div className="min-w-0">
          <h2 className="font-outfit text-lg font-bold text-claude-text-primary flex items-center space-x-2 truncate">
            <span>Audit Dashboard</span>
          </h2>
          <p className="text-xs text-claude-text-secondary truncate mt-0.5" title={document.filename}>
            File: {document.filename}
          </p>
        </div>
        
        {/* Download PDF button */}
        <button
          onClick={handleDownloadReport}
          disabled={downloading}
          className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-claude-accent hover:bg-claude-accent/90 disabled:opacity-50 text-white font-medium text-xs cursor-pointer shadow-md shadow-claude-accent/10 transition-all duration-200"
        >
          {downloading ? (
            <span className="h-3.5 w-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
          ) : (
            <Download className="h-3.5 w-3.5" />
          )}
          <span>Download PDF Audit</span>
        </button>
      </div>

      {/* Score Summary Card */}
      <div className={`p-4 rounded-xl border ${scoreBorderClass} mb-5 flex md:flex-col items-center md:items-start md:space-y-4 md:space-x-0 space-x-5 transition-colors duration-300`}>
        {/* Circle score ring widget */}
        <div className="relative h-20 w-20 flex items-center justify-center shrink-0">
          <svg className="h-full w-full transform -rotate-90">
            <circle
              cx="40"
              cy="40"
              r="34"
              className="stroke-claude-border fill-none"
              strokeWidth="6"
            />
            <circle
              cx="40"
              cy="40"
              r="34"
              className={`fill-none transition-all duration-500 ${
                overall_score >= 80 
                  ? 'stroke-emerald-500' 
                  : overall_score >= 50 
                    ? 'stroke-amber-500' 
                    : 'stroke-rose-500'
              }`}
              strokeWidth="6"
              strokeDasharray={2 * Math.PI * 34}
              strokeDashoffset={2 * Math.PI * 34 * (1 - overall_score / 100)}
            />
          </svg>
          <span className={`absolute font-outfit text-xl font-bold ${scoreColorClass}`}>
            {overall_score}
          </span>
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center space-x-1.5">
            {scoreIcon}
            <span className={`text-sm font-bold ${scoreColorClass}`}>{scoreText}</span>
          </div>
          <p className="text-xs text-claude-text-secondary leading-relaxed mt-1.5">
            {summary}
          </p>
        </div>
      </div>

      {/* Flagged compliance risks list */}
      <h3 className="font-outfit text-sm font-bold text-claude-text-primary mb-3 shrink-0">
        Flagged Compliance Risks ({risks.length})
      </h3>

      <div className="flex-1 space-y-3 pr-1">
        {risks.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-10 border border-dashed border-claude-border rounded-xl text-center text-claude-text-secondary transition-colors duration-300">
            <ShieldCheck className="h-10 w-10 text-emerald-500/80 mb-2 stroke-[1.5]" />
            <p className="text-sm font-semibold text-claude-text-primary">No Risks Detected</p>
            <p className="text-xs max-w-xs mt-1">This agreement contains standard legal templates with no major risks flagged.</p>
          </div>
        ) : (
          risks.map((risk, idx) => {
            const isExpanded = expandedRiskIdx === idx;
            
            // Map risk colors
            let riskBorder = '';
            let riskTitleBg = '';
            let riskTitleText = '';
            
            if (risk.severity_color === 'red' || risk.severity?.toUpperCase() === 'HIGH') {
              riskBorder = isExpanded ? 'border-rose-500/30' : 'border-rose-500/20';
              riskTitleBg = 'bg-rose-500/5';
              riskTitleText = 'text-rose-600 dark:text-rose-400';
            } else if (risk.severity_color === 'yellow' || risk.severity?.toUpperCase() === 'MEDIUM') {
              riskBorder = isExpanded ? 'border-amber-500/30' : 'border-amber-500/20';
              riskTitleBg = 'bg-amber-500/5';
              riskTitleText = 'text-amber-600 dark:text-amber-400';
            } else {
              riskBorder = isExpanded ? 'border-emerald-500/30' : 'border-emerald-500/20';
              riskTitleBg = 'bg-emerald-500/5';
              riskTitleText = 'text-emerald-600 dark:text-emerald-400';
            }

            return (
              <div 
                key={idx}
                className={`border rounded-xl overflow-hidden transition-all duration-300 ${riskBorder}`}
              >
                {/* Header block (clickable to toggle expand) */}
                <div 
                  onClick={() => toggleRiskExpand(idx)}
                  className={`flex items-center justify-between p-3.5 cursor-pointer transition-colors duration-300 ${riskTitleBg}`}
                >
                  <div className="flex items-center space-x-2.5 min-w-0 flex-1">
                    <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded border ${
                      risk.severity_color === 'red' 
                        ? 'border-rose-500/20 text-rose-500' 
                        : risk.severity_color === 'yellow'
                          ? 'border-amber-500/20 text-amber-500'
                          : 'border-emerald-500/20 text-emerald-500'
                    }`}>
                      {risk.severity}
                    </span>
                    <span className="text-sm font-bold text-claude-text-primary truncate">
                      {risk.category}
                    </span>
                  </div>
                  {isExpanded ? (
                    <ChevronUp className="h-4.5 w-4.5 text-claude-text-secondary shrink-0" />
                  ) : (
                    <ChevronDown className="h-4.5 w-4.5 text-claude-text-secondary shrink-0" />
                  )}
                </div>

                {/* Collapsible Details Content */}
                {isExpanded && (
                  <div className="p-4 border-t border-claude-border bg-claude-sidebar/20 space-y-4 text-xs leading-relaxed transition-colors duration-300">
                    {/* Raw Clause quote */}
                    <div className="p-3 bg-claude-card border border-claude-border rounded-lg text-claude-text-primary italic font-serif">
                      "{risk.clause_text}"
                    </div>

                    {/* Risk explanation */}
                    <div>
                      <p className="font-bold text-claude-text-primary mb-1">Risk Analysis</p>
                      <p className="text-claude-text-secondary leading-relaxed">{risk.explanation}</p>
                    </div>

                    {/* Precedent / Citation (Brave Search Results) */}
                    {risk.citation && risk.citation !== 'N/A' && (
                      <div className="p-3 bg-indigo-500/5 border border-indigo-500/10 rounded-lg">
                        <div className="flex items-center space-x-1.5 font-bold text-indigo-600 dark:text-indigo-400 mb-1 font-outfit text-xs">
                          <ExternalLink className="h-3.5 w-3.5" />
                          <span>Legal Precedent & Citations</span>
                        </div>
                        <p className="text-claude-text-secondary leading-relaxed font-mono text-[10px] bg-slate-500/5 dark:bg-slate-500/10 p-2 rounded border border-slate-500/10 mt-1 max-h-24 overflow-y-auto whitespace-pre-line">
                          {risk.citation}
                        </p>
                      </div>
                    )}

                    {/* Suggested Negotiation rewrite */}
                    <div className="p-3.5 bg-emerald-500/5 border border-emerald-500/10 rounded-lg">
                      <p className="font-bold text-emerald-600 dark:text-emerald-400 mb-1">Recommended Negotiation Suggestion</p>
                      <p className="text-claude-text-secondary leading-relaxed">{risk.suggestion}</p>
                    </div>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

import ReactMarkdown from 'react-markdown'
import rehypeSanitize from 'rehype-sanitize'
import remarkGfm from 'remark-gfm'

/**
 * Renders the final report as Markdown.
 *
 * rehype-sanitize is mandatory: report content is synthesized from web pages
 * fetched by researchers, so unfiltered HTML would be an XSS vector.
 */
export default function ReportView({ report }: { report: string }) {
  return (
    <div className="report">
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>
        {report}
      </ReactMarkdown>
    </div>
  )
}

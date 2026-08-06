import { useState, useRef, useEffect } from 'react'
import { GLOSSARY } from '../data/glossary'

interface ExplainerProps {
  termId: string
  children: React.ReactNode
}

export default function Explainer({ termId, children }: ExplainerProps) {
  const [open, setOpen] = useState(false)
  const term = GLOSSARY[termId]
  const popoverRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (popoverRef.current && !popoverRef.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    if (open) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [open])

  if (!term) return <>{children}</>

  return (
    <span className="explainer-anchor">
      <span 
        className="explainer-trigger" 
        onClick={() => setOpen(!open)}
        title={term.shortDef}
      >
        {children} <span className="explainer-icon">?</span>
      </span>
      
      {open && (
        <div className="explainer-popover panel" ref={popoverRef}>
          <div className="explainer-head">
            <strong>{term.term}</strong>
            <button className="explainer-close" onClick={() => setOpen(false)}>×</button>
          </div>
          <p className="explainer-short">{term.shortDef}</p>
          <p className="explainer-long">{term.longDef}</p>
        </div>
      )}
    </span>
  )
}

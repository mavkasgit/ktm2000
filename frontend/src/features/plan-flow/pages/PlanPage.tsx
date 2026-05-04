import { useState } from "react"
import { Beaker, FileSpreadsheet } from "lucide-react"
import { ImportWizard } from "../ImportWizard"
import { Button } from "@/shared/ui"

export function PlanPage() {
  const [importOpen, setImportOpen] = useState(false)
  const [testImportOpen, setTestImportOpen] = useState(false)

  return (
    <>
      <header className="page-header">
        <div>
          <h1 className="page-title">План и запуск</h1>
          <p className="page-subtitle">Импорт производственного плана из Excel и запуск в производство.</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => setTestImportOpen(true)}>
            <Beaker className="h-4 w-4 mr-2" />
            Тестовый импорт
          </Button>
          <Button variant="outline" onClick={() => setImportOpen(true)}>
            <FileSpreadsheet className="h-4 w-4 mr-2" />
            Импорт плана
          </Button>
        </div>
      </header>

      <ImportWizard open={importOpen} onClose={() => setImportOpen(false)} onSuccess={() => {}} />
      <ImportWizard open={testImportOpen} onClose={() => setTestImportOpen(false)} onSuccess={() => {}} mode="test" />
    </>
  )
}

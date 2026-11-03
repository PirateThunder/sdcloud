import { ModelWorkspacePage } from '@/fsd/pages/models/model-workspace-page'

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return <ModelWorkspacePage modelId={id} />
}

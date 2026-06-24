import { TeacherLivePage } from "../../../../../components/TeacherLivePage";

type PageProps = {
  params: Promise<{ assignmentId: string }>;
};

export default async function Page({ params }: PageProps) {
  const { assignmentId } = await params;
  return <TeacherLivePage assignmentId={assignmentId} />;
}

import { GradeEvidencePage } from "../../../../components/GradeEvidencePage";

type PageProps = {
  params: Promise<{ attemptId: string }>;
};

export default async function Page({ params }: PageProps) {
  const { attemptId } = await params;
  return <GradeEvidencePage attemptId={attemptId} />;
}

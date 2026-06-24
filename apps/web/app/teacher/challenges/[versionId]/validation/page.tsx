import { ChallengeValidationPage } from "../../../../../components/ChallengeValidationPage";

type PageProps = {
  params: Promise<{ versionId: string }>;
};

export default async function Page({ params }: PageProps) {
  const { versionId } = await params;
  return <ChallengeValidationPage versionId={versionId} />;
}

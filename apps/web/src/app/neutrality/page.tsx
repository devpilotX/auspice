import { PublishedPage, publishedMetadata } from "@/components/published-page";

export const generateMetadata = () => publishedMetadata("neutrality");

export default function Page() {
  return <PublishedPage slug="neutrality" />;
}

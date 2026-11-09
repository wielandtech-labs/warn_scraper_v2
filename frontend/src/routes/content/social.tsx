import { ContentPage } from "./ContentPage";

export function SocialPage() {
  return (
    <ContentPage
      title="Social"
      docTitle="Social — WARN Index"
      intro="Follow WARN Index for layoff data, new features, and reports."
    >
      <ul>
        <li>
          <a href="https://www.linkedin.com/company/warn-index/" rel="me">LinkedIn</a>
        </li>
        <li>
          <a href="https://bsky.app/profile/warnindex.com" rel="me">Bluesky</a>
        </li>
        <li>
          <a href="https://x.com/warnindex" rel="me">X</a>
        </li>
      </ul>
    </ContentPage>
  );
}

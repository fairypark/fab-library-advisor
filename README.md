# Fab Library Advisor

Fab Library Advisor is a Codex plugin that recommends relevant products from
the current user's own Fab library while working on Unreal Engine projects.

개발자: [fairypark](https://github.com/fairypark)

## 주요 기능

- 현재 Unreal 프로젝트와 맵의 용도·분위기를 먼저 확인합니다.
- 사용자가 보유한 Fab 에셋 중 관련성이 높은 항목을 최대 3개까지 제안합니다.
- 환경, 머티리얼, VFX, Niagara, 애니메이션, 오디오, 템플릿 및 게임 시스템을 지원합니다.
- 이미 프로젝트에 적합한 에셋이 있으면 불필요한 대형 패키지 도입을 피하도록 안내합니다.
- 확인 가능한 경우 Fab Listing ID와 공개 제품 상세 페이지 URL을 함께 저장해 추천 결과에서 바로 다시 열 수 있습니다.
- 용도·스타일·기술 특징·포함 기능을 구조화해 추천 근거와 신뢰도를 표시합니다.
- Unreal 프로젝트의 엔진 버전, 플러그인과 콘텐츠 이름을 읽어 가능한 기능 중복을 알립니다.
- 사용·즐겨찾기·제외 피드백을 개인 카탈로그에만 기록해 다음 추천 순위를 조정합니다.
- 다운로드를 요청한 에셋이 카탈로그에 없으면 My Library에서 소유 여부를 확인하고 자동 등록한 뒤 다운로드합니다.
- 구매·다운로드·프로젝트 추가는 사용자가 별도로 요청하기 전에는 수행하지 않습니다.

## 요구 사항

- [ChatGPT 데스크톱 앱](https://get.microsoft.com/installer/download/9PLM9XGG6VKS?cid=website_cta_psi)의 Codex 및 플러그인 기능
- [Node.js](https://nodejs.org/)와 [Codex CLI](https://learn.chatgpt.com/docs/codex/cli)
- Fab 통합 기능을 사용할 수 있는 Unreal Engine
- Unreal Editor의 Fab에 로그인된 Epic 계정
- Python 3.9 이상 권장

## 최신 정식 릴리스

- [Fab Library Advisor v0.3.2 릴리스 안내](https://github.com/fairypark/fab-library-advisor/releases/tag/v0.3.2)
- [fab-library-advisor-0.3.2.zip 직접 다운로드](https://github.com/fairypark/fab-library-advisor/releases/download/v0.3.2/fab-library-advisor-0.3.2.zip)

ZIP은 버전별 플러그인 패키지를 확인하거나 수동으로 보관하기 위한 파일입니다.
처음 설치하거나 업데이트할 때는 아래 공식 마켓플레이스 명령을 사용하세요.

플러그인을 사용하는 작업이 시작될 때 공개 GitHub 릴리스를 하루에 한 번만
확인합니다. 새 버전이 있으면 먼저 업데이트 여부를 묻고, 사용자가 명시적으로
승인한 경우에만 Codex의 공식 마켓플레이스 갱신 명령을 실행합니다. 개인 Fab
카탈로그와 GitHub 인증 토큰은 업데이트 확인에 사용되지 않습니다.

## GitHub에서 설치

아래 명령은 Windows 명령 프롬프트(CMD)에서 한 줄씩 실행합니다. 먼저 Codex
CLI가 설치되어 있는지 확인합니다.

```cmd
codex --version
```

명령을 찾을 수 없다면 Codex CLI를 설치하고 명령 프롬프트를 새로 여세요.

```cmd
npm install --global @openai/codex
```

이 저장소를 플러그인 마켓플레이스로 추가합니다.

```cmd
codex plugin marketplace add fairypark/fab-library-advisor
```

플러그인을 설치합니다.

```cmd
codex plugin add fab-library-advisor@fairypark
```

Codex 또는 ChatGPT 데스크톱 앱을 다시 시작한 뒤 새 작업을 만드세요.

데스크톱 앱의 Plugins 화면에서도 `Fairypark` 마켓플레이스를 선택해
Fab Library Advisor를 확인할 수 있습니다.

## 기존 사용자 업데이트

명령 프롬프트에서 Fairypark 마켓플레이스를 갱신합니다.

```cmd
codex plugin marketplace upgrade fairypark
```

설치된 버전을 확인합니다.

```cmd
codex plugin list
```

명령을 한 줄에 붙이지 말고 각각 따로 실행하세요. 완료 후 Codex 또는
ChatGPT 데스크톱 앱을 다시 시작하고 새 작업을 만드세요.

## 최초 동기화

1. Unreal Editor를 실행합니다.
2. **My Library | Fab**를 열고 자신의 Epic 계정으로 로그인합니다.
3. Codex에서 다음과 같이 요청합니다.

```text
내 Fab 라이브러리를 동기화해줘.
```

라이브러리 전체를 공식 API로 일괄 내려받는 방식은 아닙니다. 로그인된
My Library 화면에서 확인한 제품과 검색 결과를 중심으로 개인 색인이
점진적으로 확장됩니다. My Library 결과나 확인된 제품 링크에서 공개 Fab
상세 페이지를 식별할 수 있을 때만 Listing ID와 URL을 추가합니다. 화면에서
확인할 수 없는 ID나 비공개 Fab API의 필드는 추측하지 않습니다.

## 사용 예시

```text
현재 맵을 야간 숲으로 꾸미려고 해.
내가 보유한 Fab 에셋 중 사용할 만한 것을 추천해줘.
```

```text
Niagara로 전투 이펙트를 만들 예정이야.
내 Fab 라이브러리에서 관련 VFX를 찾아줘.
```

```text
현재 프로젝트에 사용할 수 있는 인벤토리 시스템을
내가 구매한 에셋에서 찾아줘.
```

추천 결과에는 제품명, 제작자, 보유 상태와 함께 다음 중 하나가 표시됩니다.

- 확인된 공개 Fab 제품 상세 페이지 URL
- URL이 없을 때 **My Library | Fab**에서 사용할 정확한 제품명 검색어

또한 각 후보에 다음 판단 근거가 포함됩니다.

- 어떤 필드가 검색어와 일치했는지 보여주는 `matched_on`
- `high`, `medium`, `low` 추천 신뢰도
- 메타데이터 완성도와 신선도
- 확인되지 않은 정보 목록
- 예상 통합 비용과 현재 프로젝트와의 가능한 중복 신호

로컬 추천은 다음처럼 실행할 수 있습니다.

```powershell
python <skill-dir>/scripts/catalog.py --catalog <library_catalog.json> recommend `
  "야간 숲" --project-path <Unreal-project-path> --json
```

로컬 카탈로그에서 먼저 최대 3개를 선정한 뒤, 엔진 호환성·라이선스·현재
다운로드 가능 여부가 필요한 경우에만 해당 후보의 공개 상세 페이지를
확인합니다. 모든 제품 페이지를 매번 읽지 않으므로 추천 속도와 최신성의
균형을 유지합니다.

다운로드를 명시적으로 요청한 제품이 카탈로그에 없으면 로그인된
**My Library | Fab**에서 정확한 제품을 찾습니다. 소유한 제품이 하나로
확인될 때만 최소 메타데이터를 자동 등록하고 검증한 뒤 다운로드합니다.
공개 제품 페이지에만 있거나 결과가 모호하면 자동 등록하지 않습니다.
구매·라이브러리 추가·설치·프로젝트 마이그레이션·플러그인 활성화는
다운로드 요청에 포함되지 않으며 각각 별도 승인이 필요합니다. 소유 확인
후 다운로드가 실패해도 카탈로그 기록은 유지하고, 다운로드만으로
`used` 피드백을 기록하지 않습니다.

추천된 제품 페이지를 열려면 다음처럼 요청할 수 있습니다.

```text
추천한 Forest Pack의 Fab 상세 페이지를 열어줘.
```

명령줄에서는 개인 카탈로그 경로를 지정한 뒤 다음 명령을 사용할 수 있습니다.

```powershell
python <skill-dir>/scripts/catalog.py --catalog <library_catalog.json> open "Forest Pack"
```

검증된 `listing_url`이 있으면 기본 브라우저에서 공개 제품 상세 페이지를
엽니다. 현재 플러그인에는 검증된 Unreal Editor 내부 Fab 딥링크 API가 없기
때문에 URL이 없으면 Editor를 자동 조작하지 않고 **My Library | Fab**에서
사용할 정확한 검색어를 반환합니다.

## 카탈로그 보강과 피드백

스키마 v4는 다음과 같은 선택적 특징 정보를 지원합니다.

```json
{
  "short_description": "짧고 사실적인 기능 요약",
  "product_types": ["Environment"],
  "use_cases": ["night forest"],
  "style_tags": ["realistic", "dark"],
  "technical_tags": ["Nanite", "Lumen"],
  "included_features": ["trees", "rocks"],
  "supported_engine_versions": ["5.5"],
  "supported_formats": ["Unreal Engine"],
  "integration_cost": "low",
  "metadata_sources": ["public-listing"],
  "metadata_verified_at": "2026-07-22T00:00:00+00:00"
}
```

확인된 공개 상세 페이지의 안정적인 특징을 기존 제품에 병합할 수 있습니다.

```powershell
python <skill-dir>/scripts/catalog.py --catalog <library_catalog.json> enrich `
  "Forest Pack" --use-case "night forest" --technical-tag Nanite `
  --metadata-source public-listing
```

여러 제품은 `items` 배열을 가진 JSON 파일로 한 번에 갱신할 수 있습니다.

```powershell
python <skill-dir>/scripts/catalog.py --catalog <library_catalog.json> `
  batch-upsert <observed-products.json>
```

사용 결과는 로컬 피드백으로 기록할 수 있습니다.

```powershell
python <skill-dir>/scripts/catalog.py --catalog <library_catalog.json> feedback `
  "Forest Pack" --status favorite --notes "현재 맵과 잘 맞음"
```

피드백 상태는 `unused`, `used`, `dismissed`, `favorite`이며 소유권 판정에는
영향을 주지 않습니다.

## 개인정보

배포 플러그인에는 개발자나 다른 사용자의 Fab 제품 목록이 포함되지 않습니다.
각 사용자의 카탈로그는 자신의 컴퓨터에만 저장됩니다.

Windows 기본 위치:

```text
%LOCALAPPDATA%\FabLibraryAdvisor\library_catalog.json
```

저장되는 정보:

- 제품명
- 제작자
- 카테고리
- 검색 태그
- My Library에서 확인된 보유 상태
- 선택적 Fab Listing ID
- 선택적 공개 Fab 제품 상세 페이지 URL
- 선택적 용도·스타일·기술 태그·포함 기능·형식·관찰된 엔진 버전
- 메타데이터 출처·검증 시각 및 최초·최근 My Library 확인 시각
- 사용자가 명시적으로 입력한 로컬 사용 피드백과 메모

`listing_url`은 `https://www.fab.com/listings/<Listing ID>` 형식의 공개된
영구 제품 상세 페이지 URL만 의미합니다. 실제 파일을 받는 서명된 다운로드
URL, 만료되는 CDN URL, 세션 전용 URL과는 다릅니다.

로그인 쿠키, 인증 토큰, 브라우저 저장소, 계정 식별자, 결제 정보, 라이선스
키, 서명된 다운로드 URL, 만료되는 CDN URL 및 세션 전용 URL은 저장하지
않습니다.

가격, 할인, 평점, 라이선스 조건과 현재 다운로드 가능 여부도 카탈로그에
저장하지 않습니다. 엔진 버전처럼 바뀔 수 있는 기술 정보는 검증 시각이
있는 관찰값으로만 취급하며 최종 추천 시 필요한 후보만 다시 확인합니다.

카탈로그 스키마의 새 식별·특징 필드는 선택 사항입니다. 기존
`library_catalog.json`에 `listing_id`나 `listing_url`이 없어도 그대로 읽고
검색할 수 있으며, 기존 카탈로그를 초기화하거나 일괄 마이그레이션할 필요가
없습니다. 같은 Listing ID가 다시 발견되면 새 레코드를 만들지 않고 기존
레코드의 제목·제작자·태그·특징을 병합합니다. ID가 없을 때는 기존처럼
정규화된 제품명과 제작자 조합을 사용합니다.

## 제거

Codex 또는 ChatGPT 데스크톱 앱의 Plugins 화면에서 Fab Library Advisor를
열고 **Uninstall plugin**을 선택합니다.

개인 카탈로그까지 삭제하려면 다음 폴더를 별도로 제거하세요.

```text
%LOCALAPPDATA%\FabLibraryAdvisor
```

## 링크

- Repository: <https://github.com/fairypark/fab-library-advisor>
- Developer: <https://github.com/fairypark>

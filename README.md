# Fab Library Advisor

Fab Library Advisor is a Codex plugin that recommends relevant products from
the current user's own Fab library while working on Unreal Engine projects.

개발자: [fairypark](https://github.com/fairypark)

## 주요 기능

- 현재 Unreal 프로젝트와 맵의 용도·분위기를 먼저 확인합니다.
- 사용자가 보유한 Fab 에셋 중 관련성이 높은 항목을 최대 3개까지 제안합니다.
- 환경, 머티리얼, VFX, Niagara, 애니메이션, 오디오, 템플릿 및 게임 시스템을 지원합니다.
- 이미 프로젝트에 적합한 에셋이 있으면 불필요한 대형 패키지 도입을 피하도록 안내합니다.
- 구매·다운로드·프로젝트 추가는 사용자가 별도로 요청하기 전에는 수행하지 않습니다.

## 요구 사항

- Codex 또는 ChatGPT 데스크톱 앱의 플러그인 기능
- GitHub CLI와 Codex CLI
- Fab 통합 기능을 사용할 수 있는 Unreal Engine
- Unreal Editor의 Fab에 로그인된 Epic 계정
- Python 3.9 이상 권장

## GitHub에서 설치

터미널에서 이 저장소를 플러그인 마켓플레이스로 추가합니다.

```powershell
codex plugin marketplace add fairypark/fab-library-advisor
```

플러그인을 설치합니다.

```powershell
codex plugin add fab-library-advisor@fairypark
```

Codex 또는 ChatGPT 데스크톱 앱을 다시 시작한 뒤 새 작업을 만드세요.

데스크톱 앱의 Plugins 화면에서도 `Fairypark` 마켓플레이스를 선택해
Fab Library Advisor를 확인할 수 있습니다.

## 최초 동기화

1. Unreal Editor를 실행합니다.
2. **My Library | Fab**를 열고 자신의 Epic 계정으로 로그인합니다.
3. Codex에서 다음과 같이 요청합니다.

```text
내 Fab 라이브러리를 동기화해줘.
```

라이브러리 전체를 공식 API로 일괄 내려받는 방식은 아닙니다. 로그인된
My Library 화면에서 확인한 제품과 검색 결과를 중심으로 개인 색인이
점진적으로 확장됩니다.

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

로그인 쿠키, 인증 토큰, 계정 식별자, 결제 정보, 라이선스 키 및 다운로드
URL은 저장하지 않습니다.

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

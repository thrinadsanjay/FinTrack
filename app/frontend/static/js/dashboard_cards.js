document.addEventListener("DOMContentLoaded", () => {
  const wallet = document.querySelector("[data-credit-card-wallet]");
  const hero = document.getElementById("creditCardHero");
  const stack = document.getElementById("creditCardStack");
  if (!(wallet && hero && stack)) {
    return;
  }

  const bankEl = hero.querySelector("[data-cc-bank]");
  const networkEl = hero.querySelector("[data-cc-network]");
  const outstandingEl = hero.querySelector("[data-cc-outstanding]");
  const statementEl = hero.querySelector("[data-cc-statement]");
  const dueEl = hero.querySelector("[data-cc-due]");
  const numberEl = hero.querySelector("[data-cc-number]");

  function formatMoney(value) {
    const amount = Number.parseFloat(value || "0") || 0;
    return `₹ ${amount.toFixed(2)}`;
  }

  function readCard(node) {
    return {
      id: node.dataset.cardId || "",
      network: node.dataset.cardNetwork || "other",
      networkLabel: node.dataset.cardNetworkLabel || "CARD",
      networkLogo: node.dataset.cardNetworkLogo || "",
      bankName: node.dataset.cardBankName || "Bank",
      numberHint: node.dataset.cardNumberHint || "•••• 4821",
      outstanding: node.dataset.cardOutstanding || "0",
      statementBalance: node.dataset.cardStatementBalance || "0",
      dueLabel: node.dataset.cardPaymentDueLabel || "Not set",
    };
  }

  function buildNetworkMarkup(card, heroMode = false) {
    if (card.networkLogo) {
      return `<img src="${card.networkLogo}" alt="${card.networkLabel}">`;
    }
    const extraClass = heroMode ? " data-cc-network-text" : "";
    return `<span${extraClass}>${card.networkLabel}</span>`;
  }

  function writeHero(card) {
    hero.dataset.cardId = card.id;
    hero.dataset.cardNetwork = card.network;
    hero.dataset.cardNetworkLabel = card.networkLabel;
    hero.dataset.cardNetworkLogo = card.networkLogo;
    hero.dataset.cardBankName = card.bankName;
    hero.dataset.cardNumberHint = card.numberHint;
    hero.dataset.cardOutstanding = card.outstanding;
    hero.dataset.cardStatementBalance = card.statementBalance;
    hero.dataset.cardPaymentDueLabel = card.dueLabel;
    hero.className = `credit-card-wallet__hero network-${card.network} is-swapping`;
    if (bankEl) bankEl.textContent = card.bankName;
    if (networkEl) networkEl.innerHTML = buildNetworkMarkup(card, true);
    if (numberEl) numberEl.textContent = card.numberHint;
    if (outstandingEl) outstandingEl.textContent = formatMoney(card.outstanding);
    if (statementEl) statementEl.textContent = formatMoney(card.statementBalance);
    if (dueEl) dueEl.textContent = card.dueLabel;
    requestAnimationFrame(() => {
      window.setTimeout(() => hero.classList.remove("is-swapping"), 140);
    });
  }

  function createMini(card) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `credit-card-wallet__mini network-${card.network}`;
    button.dataset.cardId = card.id;
    button.dataset.cardNetwork = card.network;
    button.dataset.cardNetworkLabel = card.networkLabel;
    button.dataset.cardNetworkLogo = card.networkLogo;
    button.dataset.cardBankName = card.bankName;
    button.dataset.cardNumberHint = card.numberHint;
    button.dataset.cardOutstanding = card.outstanding;
    button.dataset.cardStatementBalance = card.statementBalance;
    button.dataset.cardPaymentDueLabel = card.dueLabel;
    button.innerHTML = `
      <span class="credit-card-wallet__bank">${card.bankName}</span>
      <span class="credit-card-wallet__network">${buildNetworkMarkup(card)}</span>
    `;
    return button;
  }

  const orderedCards = (() => {
    const initialMiniCards = Array.from(stack.querySelectorAll(".credit-card-wallet__mini")).map(readCard);
    if (!initialMiniCards.length) {
      return [readCard(hero)];
    }
    const [previousCard, ...followingCards] = initialMiniCards;
    return [previousCard, readCard(hero), ...followingCards];
  })();

  let activeCardId = hero.dataset.cardId || orderedCards[0]?.id || "";
  let isAnimating = false;

  function getActiveIndex() {
    const index = orderedCards.findIndex((card) => card.id === activeCardId);
    return index === -1 ? 0 : index;
  }

  function buildStackCards(activeIndex) {
    const count = orderedCards.length;
    if (count <= 1) {
      return [];
    }
    const previousIndex = (activeIndex - 1 + count) % count;
    const stackCards = [orderedCards[previousIndex]];
    for (let step = 1; step <= count - 2; step += 1) {
      stackCards.push(orderedCards[(activeIndex + step) % count]);
    }
    return stackCards;
  }

  function writeStack(cards) {
    stack.innerHTML = "";
    cards.forEach((card) => {
      stack.appendChild(createMini(card));
    });
  }

  function renderActiveCard() {
    const activeIndex = getActiveIndex();
    writeHero(orderedCards[activeIndex]);
    writeStack(buildStackCards(activeIndex));
  }

  function rotateToCard(targetId, animateNode) {
    if (!targetId || isAnimating || targetId === activeCardId) {
      return;
    }

    const targetIndex = orderedCards.findIndex((card) => card.id === targetId);
    if (targetIndex === -1) {
      return;
    }

    isAnimating = true;
    if (animateNode) {
      animateNode.classList.add("is-promoting");
    }
    hero.classList.add("is-rotating-out");

    window.setTimeout(() => {
      activeCardId = orderedCards[targetIndex].id;
      renderActiveCard();
      window.setTimeout(() => {
        hero.classList.remove("is-rotating-out");
        isAnimating = false;
      }, 180);
    }, 130);
  }

  stack.addEventListener("click", (event) => {
    const target = event.target.closest(".credit-card-wallet__mini");
    if (!target) {
      return;
    }
    rotateToCard(target.dataset.cardId, target);
  });

  hero.addEventListener("click", () => {
    if (orderedCards.length <= 1) {
      return;
    }
    const nextIndex = (getActiveIndex() + 1) % orderedCards.length;
    const nextId = orderedCards[nextIndex]?.id;
    rotateToCard(nextId, null);
  });

  hero.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") {
      return;
    }
    event.preventDefault();
    if (orderedCards.length <= 1) {
      return;
    }
    const nextIndex = (getActiveIndex() + 1) % orderedCards.length;
    const nextId = orderedCards[nextIndex]?.id;
    rotateToCard(nextId, null);
  });

  renderActiveCard();
});

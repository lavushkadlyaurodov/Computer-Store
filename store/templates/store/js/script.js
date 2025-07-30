document.addEventListener('DOMContentLoaded', function() {
    // Обновление цены при выборе товара
    const productSelect = document.getElementById('id_product');
    const priceInput = document.getElementById('id_price');

    if (productSelect && priceInput) {
        productSelect.addEventListener('change', function() {
            const productId = this.value;
            if (productId) {
                fetch(`/get-product-price/${productId}/`)
                    .then(response => response.json())
                    .then(data => {
                        priceInput.value = data.price;
                    });
            }
        });
    }
});
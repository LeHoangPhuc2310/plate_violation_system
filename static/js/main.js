$(document).ready(function () {

    // ========================================
    // 1) UPLOAD VIDEO
    // ========================================
    $("#uploadForm").on("submit", function (e) {
        e.preventDefault();

        let file = $("#videoInput")[0].files[0];
        if (!file) {
            alert("Chưa chọn file!");
            return;
        }

        let formData = new FormData();
        formData.append("video", file);

        $.ajax({
            url: "/upload_video",
            type: "POST",
            data: formData,
            processData: false,
            contentType: false,

            success: function (res) {
                if (res.status === "ok") {
                    alert("Upload thành công!");
                    $("#liveFrame").attr("src", "/video_feed?" + Date.now());
                } else {
                    alert("Upload lỗi!");
                }
            }
        });
    });

    // ========================================
    // 2) OPEN CAMERA
    // ========================================
    $("#startCamera").click(function () {
        $.get("/open_camera", function (res) {
            if (res.status === "ok") {
                $("#cameraFeed").attr("src", "/video_feed?" + Date.now());
            }
        });
    });

    $("#stopCamera").click(function () {
        $.get("/stop_camera", function (res) {
            if (res.status === "ok") {
                $("#cameraFeed").attr("src", "");
            }
        });
    });


    // ========================================
    // 3) LOAD HISTORY
    // ========================================
    function loadHistory() {
        fetch("/violations")
            .then(res => res.json())
            .then(data => {
                let html = "";

                data.forEach(v => {
                    html += `
                    <tr>
                        <td>${v.plate}</td>
                        <td>${v.owner_name || "Không rõ"}</td>
                        <td>${v.address || "Không rõ"}</td>
                        <td>${v.phone || "Không rõ"}</td>
                        <td>${v.speed}</td>
                        <td>${v.speed_limit}</td>
                        <td>${v.time}</td>
                        <td><img src="/static/uploads/${v.image}" class="history-img"></td>
                    </tr>`;
                });

                $("#history-table").html(html);
            });
    }

    loadHistory();


    // ========================================
    // 4) LIVE DASHBOARD UPDATE
    // ========================================
    function updateStats() {
        fetch("/get_stats")
            .then(res => res.json())
            .then(data => {
                $("#total").text(data.total);
                $("#vehicles").text(data.vehicles);
                $("#avg_speed").text(data.avg_speed);
            });
    }

    setInterval(updateStats, 2000);
    updateStats();


    // ========================================
    // 5) SSE – VI PHẠM MỚI THÊM TỰ ĐỘNG
    // ========================================
    const eventSource = new EventSource("/stream");

    eventSource.onmessage = function (event) {
        let v = JSON.parse(event.data);

        let row = `
        <tr>
            <td>${v.plate}</td>
            <td>${v.owner_name || "Không rõ"}</td>
            <td>${v.address || "Không rõ"}</td>
            <td>${v.phone || "Không rõ"}</td>
            <td>${v.speed}</td>
            <td>${v.speed_limit}</td>
            <td>${v.time}</td>
            <td><img src="/static/uploads/${v.image}" class="history-img"></td>
        </tr>`;

        $("#history-table").prepend(row);
    };
function showAlert(message) {
    const alertBox = document.getElementById("alert-box");
    alertBox.innerText = message;
    alertBox.classList.remove("d-none");
}
$(document).ready(function () {

    $("#plateInput").on("input", function () {
        let keyword = $(this).val().trim();

        if (keyword.length < 1) {
            $("#suggestions").hide();
            return;
        }

        $.ajax({
            url: "/autocomplete",
            method: "GET",
            data: { q: keyword },
            success: function (data) {
                let box = $("#suggestions");
                box.empty();

                if (data.length === 0) {
                    box.hide();
                    return;
                }

                data.forEach(function (item) {
                    box.append(`<div class="suggest-item">${item}</div>`);
                });

                box.show();
            }
        });
    });

//    DUNG VIDEO
$("#stopVideoBtn").click(function () {
    $.get("/stop_video_upload", function (res) {
        if (res.status === "ok") {
            $("#liveFrame").attr("src", "");  // xóa khung hình
            alert("Video đã dừng.");
        }
    });
});

    // Khi click chọn trong danh sách
    $(document).on("click", ".suggest-item", function () {
        $("#plateInput").val($(this).text());
        $("#suggestions").hide();
    });

    // Click ra ngoài thì ẩn
    $(document).click(function (e) {
        if (!$(e.target).closest("#plateInput").length) {
            $("#suggestions").hide();
        }
    });

});

});
